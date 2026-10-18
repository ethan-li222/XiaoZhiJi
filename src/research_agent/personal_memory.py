"""Independent personal notes and explicit, evidence-linked memory consolidation."""

import asyncio
import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from .models import new_id, now


class HighlightRect(BaseModel):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def inside_page(self):
        if self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise ValueError("高亮坐标超出页面")
        return self


class PersonalNoteParams(BaseModel):
    id: str | None = None
    revision: int | None = Field(default=None, ge=1)
    title: str = Field(default="", max_length=300)
    text: str = Field(default="", max_length=30000)
    category: Literal["knowledge", "event", "decision", "preference", "insight", "value"] = (
        "knowledge"
    )
    layer: Literal["context", "behavior", "cognition", "core", "intent"] = "context"
    status: Literal["inbox", "confirmed", "archived"] = "inbox"
    notebook: str = Field(default="收件箱", min_length=1, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=30)
    source_url: str = Field(default="", max_length=3000)
    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    selection: str = Field(default="", max_length=15000)
    rects: list[HighlightRect] = Field(default_factory=list, max_length=200)
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    event_date: date | None = None
    origin: Literal["manual", "review"] = "manual"
    operation_id: str | None = None


class PersonalSearchParams(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=12, ge=1, le=50)


class PersonalReviewParams(BaseModel):
    days: int = Field(default=30, ge=1, le=366)


class PersonalExportParams(BaseModel):
    pass


class PersonalDeleteParams(BaseModel):
    id: str
    revision: int = Field(ge=1)


class ReadingPosition(BaseModel):
    page: int = Field(ge=1, le=50000)


def today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


PERSONAL_PARAMS = {
    "memory.note.save": PersonalNoteParams,
    "memory.search": PersonalSearchParams,
    "memory.review": PersonalReviewParams,
    "memory.export": PersonalExportParams,
    "memory.note.delete": PersonalDeleteParams,
}


def normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


class PersonalMemory:
    def __init__(self, store, embedder):
        self.store, self.embedder = store, embedder

    async def call(self, action, params):
        return await getattr(self, action.removeprefix("memory.").replace(".", "_"))(**params)

    async def note_save(self, **params):
        operation = params.pop("operation_id", None)
        if operation:
            with self.store.connect() as db:
                done = db.execute(
                    "SELECT item_id FROM operations WHERE id=?", (operation,)
                ).fetchone()
            if done:
                return {"entry": self.store.get(done[0], "personal_note"), "warnings": []}
        identifier, revision = params.pop("id", None), params.pop("revision", None)
        old = self.store.get(identifier, "personal_note") if identifier else None
        if old and revision is None:
            raise ValueError("修改笔记需要当前版本，请刷新后重试")
        if not old and revision is not None:
            raise ValueError("笔记不存在，无法更新")
        if not params["text"].strip() and not params["selection"].strip():
            raise ValueError("笔记正文或原文选段不能为空")
        if params["layer"] == "core" and params["origin"] != "manual":
            raise ValueError("核心层只接受本人手动填写，不接受自动提炼")
        sources = []
        for source_id in dict.fromkeys(params["source_ids"]):
            try:
                sources.append(self.store.get(source_id, "personal_note"))
            except ValueError:
                if not old or source_id not in old["source_ids"]:
                    raise
        if identifier and identifier in params["source_ids"]:
            raise ValueError("笔记不能引用自身")
        if params["origin"] == "review" and not old:
            if any(s["status"] != "confirmed" for s in sources):
                raise ValueError("复盘来源须为已确认的记录")
            if params["layer"] == "behavior":
                valid = [
                    s
                    for s in sources
                    if s["layer"] == "context" and s["category"] in {"event", "decision"}
                ]
                if len({s["event_date"] for s in valid}) < 3:
                    raise ValueError("行为层候选至少需要三个不同日期的情境事件")
            elif params["layer"] == "cognition":
                if len({s["id"] for s in sources if s["layer"] == "behavior"}) < 2:
                    raise ValueError("认知层候选至少需要两条已确认行为记录")
            else:
                raise ValueError("复盘候选只可进入行为层或认知层")
        document_id, quote = params["document_id"], params["selection"].strip()
        evidence_ids = []
        if document_id:
            try:
                self.store.get(document_id, "document")
                missing_document = False
            except ValueError:
                if not old or any(
                    params[k] != old[k] for k in ("document_id", "page", "selection", "rects")
                ):
                    raise
                missing_document = True
                evidence_ids = old["evidence_ids"]
            chunks = [
                c
                for c in self.store.list("chunk", document_id)
                if params["page"] is None or c["page"] == params["page"]
            ]
            if not missing_document and params["page"] is not None and not chunks:
                raise ValueError("文档中不存在该页")
            if quote and not missing_document:
                if normalized(quote) not in normalized("\n".join(c["text"] for c in chunks)):
                    raise ValueError("选段未在原文中定位，请重新选择")
                evidence_ids = [
                    c["id"] for c in chunks if normalized(quote) in normalized(c["text"])
                ] or [c["id"] for c in chunks[:10]]
        elif quote or params["rects"] or params["page"] is not None:
            raise ValueError("原文选段和高亮需要关联文档")
        if params["rects"] and (not quote or params["page"] is None):
            raise ValueError("高亮需要选段和页码")
        identifier = identifier or "note-" + (
            hashlib.sha256(operation.encode()).hexdigest()[:24] if operation else new_id()
        )
        entry = {
            **params,
            "id": identifier,
            "selection": quote,
            "source_ids": list(dict.fromkeys(params["source_ids"])),
            "evidence_ids": evidence_ids,
            "created_at": old["created_at"] if old else now(),
            "updated_at": now(),
            "event_date": str(params.get("event_date") or today()),
            "revision": (revision or 0) + 1,
            "tags": list(dict.fromkeys(t.strip() for t in params["tags"] if t.strip())),
        }
        entry["title"] = params["title"].strip() or (params["text"].strip() or quote)[:80]
        text = "\n".join([entry["title"], entry["text"], quote, entry["notebook"], *entry["tags"]])
        vector, warnings = None, []
        try:
            vector = (await asyncio.to_thread(self.embedder.encode, [text]))[0]
        except (ValueError, OSError) as exc:
            warnings.append(str(exc))
        # Independent notes survive deletion of their original document, with a broken-source marker.
        entry = self.store.put(
            "personal_note",
            entry,
            text=text,
            vector=vector,
            model=self.embedder.identity if vector else None,
            expected_revision=revision,
            operation_id=operation,
        )
        return {"entry": entry, "warnings": warnings}

    async def search(self, query, limit=12):
        vector, warnings = None, []
        try:
            vector = (await asyncio.to_thread(self.embedder.encode, [query], True))[0]
        except (ValueError, OSError) as exc:
            warnings.append(str(exc))
        options = {
            "limit": limit,
            "vector": vector,
            "model": self.embedder.identity if vector else None,
        }
        personal = self.store.search(query, "personal_note", **options)
        reading = self.store.search(query, "knowledge", **options)
        return {"personal_entries": personal, "entries": reading, "warnings": warnings}

    async def review(self, days=30):
        cutoff = today() - timedelta(days=days - 1)
        notes = [
            n
            for n in self.store.list("personal_note")
            if n["status"] == "confirmed"
            and cutoff <= date.fromisoformat(n["event_date"]) <= today()
        ]
        grouped = defaultdict(list)
        for n in notes:
            for tag in n["tags"]:
                grouped[tag].append(n)
        candidates = []
        for tag, records in sorted(grouped.items()):
            for target, eligible in [
                (
                    "behavior",
                    [
                        n
                        for n in records
                        if n["layer"] == "context" and n["category"] in {"event", "decision"}
                    ],
                ),
                ("cognition", [n for n in records if n["layer"] == "behavior"]),
            ]:
                count = (
                    len({n["event_date"] for n in eligible})
                    if target == "behavior"
                    else len(eligible)
                )
                if count >= (3 if target == "behavior" else 2):
                    candidates.append(
                        {
                            "title": "关于「" + tag + "」的待复核主题",
                            "layer": target,
                            "source_ids": [n["id"] for n in eligible[:30]],
                            "tags": [tag],
                            "text": "共同标签：" + tag + "。请结合原始情境自行总结适用条件与反例。",
                            "reason": "同标签的不同日期记录"
                            if target == "behavior"
                            else "同标签的已确认行为记录",
                        }
                    )
        return {
            "personal_candidates": candidates[:20],
            "warnings": [
                "标签重复只提示值得复核的主题，不证明习惯或因果关系；采纳后仍进入待整理，不自动更新核心层。"
            ],
        }

    async def export(self):
        notes = self.store.list("personal_note")
        lines = ["# 个人知识与记忆", ""]
        for n in notes:
            lines += [
                "## " + n["title"],
                f"ID: {n['id']} | 层级: {n['layer']} | 状态: {n['status']} | 笔记本: {n['notebook']}",
                n["text"],
                "原文：" + n["selection"],
                "来源：" + n["source_url"],
                "引用记录：" + ", ".join(n["source_ids"]),
                "",
            ]
        return {"personal_entries": notes, "markdown": "\n".join(lines), "exported_at": now()}

    async def note_delete(self, id, revision):
        # Atomic version check prevents deleting a concurrently edited note.
        with self.store.connect() as db:
            import json

            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM items WHERE id=? AND kind='personal_note'", (id,)
            ).fetchone()
            if not row or json.loads(row[0])["revision"] != revision:
                raise ValueError("笔记已被修改或删除，请刷新后重试")
            db.execute("DELETE FROM fulltext WHERE id=?", (id,))
            db.execute("DELETE FROM items WHERE id=?", (id,))
        return {"deleted": id}
