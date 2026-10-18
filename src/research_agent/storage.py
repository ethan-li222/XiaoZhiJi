import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import now


def tokens(text: str) -> str:
    import jieba

    jieba.setLogLevel(logging.ERROR)
    return " ".join(x for x in jieba.cut(text.lower()) if re.search(r"\w", x))


class Store:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "research.sqlite3"
        data_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, parent TEXT,
                    body TEXT NOT NULL, vector TEXT, model TEXT);
                CREATE INDEX IF NOT EXISTS items_kind_parent ON items(kind,parent);
                CREATE VIRTUAL TABLE IF NOT EXISTS fulltext USING fts5(id UNINDEXED, text);
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY, body TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS activities (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, item_id TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(
        self,
        kind,
        item,
        *,
        parent=None,
        text=None,
        vector=None,
        model=None,
        expected_revision=None,
        if_absent=False,
        operation_id=None,
        event=None,
    ):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if operation_id:
                operation = db.execute(
                    "SELECT item_id FROM operations WHERE id=?", (operation_id,)
                ).fetchone()
                if operation:
                    row = db.execute(
                        "SELECT body FROM items WHERE id=?", (operation[0],)
                    ).fetchone()
                    if not row:
                        raise ValueError("本次操作保存的记录已删除，不能通过重试恢复")
                    return json.loads(row[0])
            existing = db.execute("SELECT body FROM items WHERE id=?", (item["id"],)).fetchone()
            if if_absent and existing:
                return json.loads(existing[0])
            if (
                kind == "knowledge"
                and not db.execute(
                    "SELECT 1 FROM items WHERE id=? AND kind='document'", (parent,)
                ).fetchone()
            ):
                raise ValueError("来源文章已删除，无法保存知识")
            if expected_revision is not None and (
                not existing or json.loads(existing[0]).get("revision", 1) != expected_revision
            ):
                raise ValueError("记录已被修改或删除，请刷新后重试")
            db.execute(
                "INSERT OR REPLACE INTO items VALUES(?,?,?,?,?,?)",
                (
                    item["id"],
                    kind,
                    parent,
                    json.dumps(item, ensure_ascii=False),
                    json.dumps(vector) if vector is not None else None,
                    model,
                ),
            )
            db.execute("DELETE FROM fulltext WHERE id=?", (item["id"],))
            if text:
                db.execute("INSERT INTO fulltext VALUES(?,?)", (item["id"], tokens(text)))
            if operation_id:
                db.execute("INSERT INTO operations VALUES(?,?)", (operation_id, item["id"]))
            if event:
                db.execute(
                    "INSERT OR IGNORE INTO activities VALUES(?,?)",
                    (event["id"], json.dumps(event, ensure_ascii=False)),
                )
        return item

    def record_activity(self, event):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO activities VALUES(?,?)",
                (event["id"], json.dumps(event, ensure_ascii=False)),
            )

    def activities(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM activities")]

    def get(self, item_id, kind=None):
        with self.connect() as db:
            row = db.execute("SELECT kind,body FROM items WHERE id=?", (item_id,)).fetchone()
        if not row or (kind and row["kind"] != kind):
            raise ValueError(f"找不到 {kind or '记录'}：{item_id}")
        return json.loads(row["body"])

    def list(self, kind, parent=None):
        sql = "SELECT body FROM items WHERE kind=?"
        args = [kind]
        if parent is not None:
            sql += " AND parent=?"
            args.append(parent)
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute(sql, args)]

    def delete(self, item_id):
        with self.connect() as db:
            db.execute(
                "DELETE FROM fulltext WHERE id IN (SELECT id FROM items WHERE id=? OR parent=?)",
                (item_id, item_id),
            )
            db.execute("DELETE FROM items WHERE id=? OR parent=?", (item_id, item_id))

    def search(
        self,
        query,
        kind="chunk",
        parent=None,
        vector=None,
        model=None,
        limit=6,
        status=None,
        tag=None,
    ):
        terms = list(dict.fromkeys(tokens(query).split()))[:32]
        expr = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        where = "i.kind=?" + (" AND i.parent=?" if parent else "")
        args = [kind] + ([parent] if parent else [])
        if kind in {"knowledge", "personal_note"}:
            if status:
                where += " AND COALESCE(json_extract(i.body,'$.status'),'inbox')=?"
                args.append(status)
            else:
                where += " AND COALESCE(json_extract(i.body,'$.status'),'inbox')!='archived'"
            if tag:
                where += " AND EXISTS (SELECT 1 FROM json_each(i.body,'$.tags') WHERE value=?)"
                args.append(tag)
        scores = {}
        with self.connect() as db:
            if expr:
                rows = db.execute(
                    "SELECT i.id FROM fulltext JOIN items i ON i.id=fulltext.id "
                    f"WHERE fulltext MATCH ? AND {where} ORDER BY bm25(fulltext) LIMIT 30",
                    [expr, *args],
                ).fetchall()
                for rank, r in enumerate(rows):
                    scores[r["id"]] = 1 / (60 + rank + 1)
            if vector is not None:
                import numpy as np

                query_vec = np.array(vector)
                candidates = db.execute(
                    f"SELECT i.id,i.vector FROM items i WHERE {where} AND model=? AND vector IS NOT NULL",
                    [*args, model],
                ).fetchall()
                ranked = []
                for r in candidates:
                    v = np.array(json.loads(r["vector"]))
                    if v.shape == query_vec.shape:
                        cosine = float(
                            np.dot(v, query_vec)
                            / max(1e-9, np.linalg.norm(v) * np.linalg.norm(query_vec))
                        )
                        if kind not in {"knowledge", "personal_note"} or cosine > 0.3:
                            ranked.append((r["id"], cosine))
                for rank, (item_id, _) in enumerate(sorted(ranked, key=lambda x: -x[1])[:30]):
                    scores[item_id] = scores.get(item_id, 0) + 1 / (60 + rank + 1)
        return [
            self.get(i) | {"retrieval_score": s}
            for i, s in sorted(scores.items(), key=lambda x: -x[1])[:limit]
        ]

    def task_put(self, task):
        task["updated_at"] = now()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO tasks VALUES(?,?)",
                (task["id"], json.dumps(task, ensure_ascii=False)),
            )

    def task_get(self, task_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ValueError(f"找不到任务：{task_id}")
        return json.loads(row[0])

    def task_list(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM tasks")]

    def append_history(self, session_id, entry):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM items WHERE id=? AND kind='session'", (session_id,)
            ).fetchone()
            if not row:
                raise ValueError("阅读会话已删除")
            session = json.loads(row[0])
            if not any(h.get("task_id") == entry["task_id"] for h in session["history"]):
                session["history"].append(entry)
                db.execute(
                    "UPDATE items SET body=? WHERE id=?",
                    (json.dumps(session, ensure_ascii=False), session_id),
                )

    def claim(self, task_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = json.loads(
                db.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
            )
            if task["status"] in {"running", "completed"}:
                raise ValueError("任务已运行或完成")
            task.update(status="running", error=None, updated_at=now())
            db.execute(
                "UPDATE tasks SET body=? WHERE id=?",
                (json.dumps(task, ensure_ascii=False), task_id),
            )
            return task
