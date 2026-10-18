"""Conversation context and durable turns, without implicit access to personal memory."""

import asyncio
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .models import new_id, now


class ChatParams(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)
    message: str = Field(min_length=1, max_length=12000)
    scope: Literal["none", "knowledge", "personal"] = "none"
    project_id: str | None = None
    document_id: str | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=6)
    document_mode: Literal["auto", "selected"] = "auto"
    operation_id: str | None = None

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("消息不能为空白")
        return value.strip()


class ChatReply(BaseModel):
    answer: str = Field(min_length=1, max_length=30000)
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    followups: list[str] = Field(default_factory=list, max_length=3)


def new_session():
    return {
        "id": "chat-" + new_id(),
        "title": "新对话",
        "revision": 1,
        "turns": [],
        "created_at": now(),
        "updated_at": now(),
    }


class ChatContext:
    def __init__(self, store, embedder):
        self.store, self.embedder = store, embedder

    async def prepare(
        self,
        session_id,
        revision,
        message,
        scope="none",
        project_id=None,
        document_id=None,
        operation_id=None,
        document_ids=None,
        document_mode="auto",
    ):
        session = self.store.get(session_id, "chat_session")
        completed = next(
            (t for t in session["turns"] if operation_id and t["task_id"] == operation_id), None
        )
        if completed:
            return {"completed_turn": completed, "session_id": session_id}
        if session["revision"] != revision:
            raise ValueError("会话已更新，请刷新后重试")
        if len(session["turns"]) >= 200:
            raise ValueError("该会话已达到 200 轮，请开始新对话")
        sources, warnings, doc_ids = [], [], None
        if project_id:
            project = self.store.get(project_id, "project")
            doc_ids = {
                x.get("document_id")
                for x in self.store.list("library")
                if x["project_id"] == project_id
            }
            sources.append(
                {
                    "id": project_id,
                    "record_id": project_id,
                    "kind": "project",
                    "title": project["name"],
                    "text": "研究问题："
                    + project["question"]
                    + "\n下一步："
                    + project["next_step"],
                    "url": "",
                }
            )
        selected_ids = list(
            dict.fromkeys(([document_id] if document_id else []) + (document_ids or []))
        )
        if len(selected_ids) > 6:
            raise ValueError("每轮最多指定 6 份文档")
        documents = [self.store.get(identifier, "document") for identifier in selected_ids]
        if not selected_ids and doc_ids and document_mode == "auto":
            # Search every project document before ranking; never pick the first arbitrary files.
            documents = [d for d in self.store.list("document") if d["id"] in doc_ids]
        if project_id and not selected_ids and not documents and document_mode == "auto":
            warnings.append(
                "该项目还没有可检索的已导入文档；本轮仅提供项目说明及按范围筛选的笔记。"
            )
        vector = None
        if scope != "none" or documents:
            try:
                vector = (await asyncio.to_thread(self.embedder.encode, [message], True))[0]
            except (ValueError, OSError) as exc:
                warnings.append(str(exc))
        project_chunks = []
        for document in documents:
            identifier = document["id"]
            chunks = self.store.search(
                message,
                kind="chunk",
                parent=identifier,
                vector=vector,
                model=self.embedder.identity if vector else None,
                limit=max(1, 10 // len(documents)) if selected_ids else 3,
            )
            if not chunks and selected_ids:
                chunks = self.store.list("chunk", identifier)[: max(1, 10 // len(documents))]
                warnings.append(
                    f"《{document['title']}》未命中相关段落，附上开头；全文尚未全部覆盖。"
                )
            for c in chunks:
                project_chunks.append(
                    {
                        "id": c["id"],
                        "record_id": identifier,
                        "kind": "chunk",
                        "title": document["title"],
                        "text": c["text"],
                        "url": document.get("source_url", ""),
                        "page": c.get("page"),
                        "score": c.get("retrieval_score", 0),
                    }
                )
        if not selected_ids:
            project_chunks.sort(key=lambda c: c["score"], reverse=True)
        sources.extend(project_chunks[:10])
        if scope != "none":
            for kind in ("knowledge", "personal_note"):
                candidates = self.store.search(
                    message,
                    kind,
                    vector=vector,
                    model=self.embedder.identity if vector else None,
                    limit=30,
                )
                for note in candidates:
                    if note.get("status", "inbox") != "confirmed":
                        continue
                    if (
                        kind == "personal_note"
                        and scope == "knowledge"
                        and (
                            note["category"] not in {"knowledge", "insight"}
                            or note["layer"] != "context"
                        )
                    ):
                        continue
                    if doc_ids is not None and note.get("document_id") not in doc_ids:
                        continue
                    if selected_ids and note.get("document_id") not in selected_ids:
                        continue
                    if document_mode == "selected" and not selected_ids and note.get("document_id"):
                        continue
                    if note.get("document_id"):
                        try:
                            self.store.get(note["document_id"], "document")
                        except ValueError:
                            warnings.append("已跳过来源文档失效的笔记。")
                            continue
                    sources.append(
                        {
                            "id": note["id"],
                            "record_id": note["id"],
                            "kind": kind,
                            "title": note.get("title") or note["question"],
                            "text": note.get("text")
                            if kind == "personal_note"
                            else note["answer"] + "\n" + note.get("notes", ""),
                            "url": note.get("source_url", ""),
                        }
                    )
                    if len(sources) >= 12:
                        break
        bounded, budget = [], 18000
        candidates = sources[:12]
        for index, source in enumerate(candidates):
            source["text"] = source["text"][: min(2500, budget // (len(candidates) - index))]
            if not source["text"]:
                continue
            bounded.append(source)
            budget -= len(source["text"])
        history = [
            {"user": t["message"][:2000], "assistant": t["answer"][:3000]}
            for t in session["turns"][-6:]
        ]
        return {
            "session_id": session_id,
            "revision": revision,
            "message": message,
            "history": history,
            "sources": bounded,
            "scope": scope,
            "project_id": project_id,
            "document_id": document_id,
            "document_ids": selected_ids,
            "document_mode": document_mode,
            "warnings": list(dict.fromkeys(warnings)),
            "history_truncated": len(session["turns"]) > 6,
        }


def save_turn(store, context, result, task_id):
    session = store.get(context["session_id"], "chat_session")
    if any(t["task_id"] == task_id for t in session["turns"]):
        return session
    turn = {
        "task_id": task_id,
        "message": context["message"],
        "answer": result["answer"],
        "sources": result["sources"],
        "followups": result["followups"],
        "scope": context["scope"],
        "project_id": context["project_id"],
        "document_id": context["document_id"],
        "document_ids": context.get("document_ids", []),
        "document_mode": context.get("document_mode", "auto"),
        "warnings": result["warnings"],
        "created_at": now(),
    }
    session["turns"].append(turn)
    session.update(revision=context["revision"] + 1, updated_at=now())
    if len(session["turns"]) == 1:
        session["title"] = context["message"][:50]
    return store.put(
        "chat_session", session, expected_revision=context["revision"], operation_id=task_id
    )
