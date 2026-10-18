"""Explicit knowledge curation; reading history never becomes a personal profile."""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from .models import KnowledgeEntry, now


def knowledge_text(entry):
    return "\n".join(
        [
            entry["question"],
            entry["answer"],
            entry.get("selection", ""),
            entry.get("notes", ""),
            " ".join(entry.get("tags", [])),
        ]
    )


class MemoryTools:
    def __init__(self, store, embedder):
        self.store, self.embedder = store, embedder

    async def update(self, id, revision, notes, tags, status):
        entry = KnowledgeEntry.model_validate(self.store.get(id, "knowledge")).model_dump()
        entry.update(
            notes=notes,
            tags=list(dict.fromkeys(t.strip() for t in tags if t.strip())),
            status=status,
            revision=revision + 1,
            updated_at=now(),
        )
        text = knowledge_text(entry)
        vector, warnings = None, []
        try:
            vector = (await asyncio.to_thread(self.embedder.encode, [text]))[0]
        except (ValueError, OSError) as exc:
            warnings.append(str(exc))
        entry = self.store.put(
            "knowledge",
            entry,
            parent=entry["document_id"],
            text=text,
            vector=vector,
            model=self.embedder.identity if vector else None,
            expected_revision=revision,
        )
        return {"entry": entry, "warnings": warnings}

    async def review(self, days=7):
        cutoff = datetime.now(UTC) - timedelta(days=days)
        entries = [
            KnowledgeEntry.model_validate(
                {**k, "updated_at": k.get("updated_at", k["created_at"])}
            ).model_dump()
            for k in self.store.list("knowledge")
        ]
        recent = [
            k
            for k in entries
            if k["status"] != "archived"
            and datetime.fromisoformat(k["updated_at"]).replace(tzinfo=UTC) >= cutoff
        ]
        groups = defaultdict(list)
        for entry in recent:
            for tag in set(entry["tags"]):
                groups[tag].append(entry)
        topics = [
            {
                "tag": tag,
                "count": len(items),
                "document_count": len({k["document_id"] for k in items}),
                "entries": items,
                "prompt": "比较这些笔记的适用条件、共同点与冲突；核对原文后将结论写入个人批注。",
            }
            for tag, items in sorted(groups.items(), key=lambda pair: -len(pair[1]))
            if len(items) >= 2
        ][:5]
        return {
            "days": days,
            "entries": sorted(recent, key=lambda k: k["updated_at"], reverse=True),
            "topics": topics,
            "pending_count": sum(k["status"] == "inbox" for k in recent),
            "warnings": ["复盘按标签归组，出现次数不代表结论正确；不会自动推断习惯或价值观。"],
        }

    async def export(self):
        entries = [
            KnowledgeEntry.model_validate(k).model_dump() for k in self.store.list("knowledge")
        ]
        lines = ["# 阅读知识库", "", "包含待整理、已确认和已归档卡片。", ""]
        for k in entries:
            lines += [
                f"## {k['question']}",
                f"ID: {k['id']}",
                f"状态: {k['status']} · 标签: {', '.join(k['tags'])}",
                "",
                k["answer"],
                "",
                "### 个人批注",
                k["notes"],
                "",
                "### 原文依据",
            ]
            for source in k["evidence"]:
                lines += [
                    f"- {source.get('title', '')} | {source.get('source', '')} | "
                    f"页码: {source.get('page')} | 块: {source.get('id')}",
                    source.get("text", ""),
                    "",
                ]
        return {"entries": entries, "markdown": "\n".join(lines), "exported_at": now()}
