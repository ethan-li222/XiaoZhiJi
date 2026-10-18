import asyncio
import json

import pytest
from conftest import run


async def saved(engine, source="test"):
    doc = (
        await run(
            engine,
            "documents.import",
            {"source": source, "text": "文献耦合是两篇论文共享参考文献。共引来自第三篇论文。"},
        )
    )["document"]["id"]
    answer = await run(engine, "reading.ask", {"document_id": doc, "question": "文献耦合是什么"})
    entry = (
        await run(engine, "knowledge.save", {"session_id": answer["session_id"], "tags": ["引用"]})
    )["entry"]
    return doc, answer["session_id"], entry


async def test_save_deduplicates_and_preserves_curated_notes(engine, tools):
    _, session, entry = await saved(engine)
    updated = await tools.call(
        "knowledge.update",
        dict(id=entry["id"], revision=1, notes="已核对适用条件", tags=["方法"], status="confirmed"),
    )
    again = await tools.call("knowledge.save", {"session_id": session, "turn": 0})
    assert again["entry"] == updated["entry"]
    assert len(tools.store.list("knowledge")) == 1
    with pytest.raises(ValueError, match="刷新"):
        await tools.call(
            "knowledge.update",
            dict(id=entry["id"], revision=1, notes="过期修改", tags=[], status="archived"),
        )


async def test_filters_and_only_confirmed_memory_is_recalled(engine, tools, model):
    doc, session, entry = await saved(engine)
    context = await tools.documents.retrieve(doc, "它的适用条件", session_id=session)
    assert not context["memories"]
    await tools.memory.update(entry["id"], 1, "记忆背景", ["引用"], "confirmed")
    answer = await run(
        engine,
        "reading.ask",
        {"document_id": doc, "question": "它的适用条件", "session_id": session},
    )
    assert answer["recalled_memories"][0]["id"] == entry["id"]
    assert model.calls[-1]["memories"]
    assert all(e["document_id"] == doc for e in answer["evidence"])
    assert not (await tools.call("knowledge.search", {"query": "引用", "tag": "不存在"}))["entries"]
    await tools.memory.update(entry["id"], 2, "记忆背景", ["引用"], "archived")
    assert not (await tools.documents.retrieve(doc, "文献耦合"))["memories"]
    assert not (await tools.call("knowledge.search", {"query": "引用"}))["entries"]
    assert (await tools.call("knowledge.search", {"query": "引用", "status": "archived"}))[
        "entries"
    ]


async def test_review_export_and_delete_sources(engine, tools):
    doc, _, _ = await saved(engine)
    await saved(engine, "second")
    review = await run(engine, "knowledge.review", {"days": 7})
    assert review["pending_count"] == 2
    assert review["topics"][0]["count"] == 2
    assert review["topics"][0]["document_count"] == 2
    exported = await run(engine, "knowledge.export", {})
    from pathlib import Path

    markdown = Path(exported["artifacts"]["markdown"]).read_text(encoding="utf-8")
    assert "原文依据" in markdown and "共享参考文献" in markdown
    payload = json.loads(Path(exported["artifacts"]["json"]).read_text(encoding="utf-8"))
    assert len(payload["entries"]) == 2
    await run(engine, "documents.delete", {"id": doc})
    assert not (await tools.memory.review())["topics"]
    assert len(tools.store.list("knowledge")) == 1


async def test_concurrent_updates_do_not_overwrite(engine, tools):
    _, _, entry = await saved(engine)
    results = await asyncio.gather(
        *[tools.memory.update(entry["id"], 1, str(n), [], "confirmed") for n in range(2)],
        return_exceptions=True,
    )
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert tools.store.get(entry["id"])["revision"] == 2


async def test_bounded_history_and_page_selection(engine, tools):
    doc, session_id, _ = await saved(engine)
    session = tools.store.get(session_id)
    session["history"] *= 20
    for turn in session["history"]:
        turn["answer"] = "长回答" * 1000
    tools.store.put("session", session, parent=doc)
    context = await tools.documents.retrieve(doc, "继续解释", session_id=session_id)
    assert len(context["reading_history"]) == 6
    assert all(len(h["answer"]) <= 1200 for h in context["reading_history"])
    assert context["earlier_topics"]
    context = await tools.documents.retrieve(doc, "解释", page=99, selection="文献耦合")
    assert not context["evidence"]


async def test_legacy_entry_is_editable(engine, tools):
    _, _, entry = await saved(engine)
    for key in ["status", "notes", "revision", "updated_at", "session_id", "turn_index"]:
        entry.pop(key)
    tools.store.put("knowledge", entry, parent=entry["document_id"], text=entry["answer"])
    updated = await tools.memory.update(entry["id"], 1, "旧卡片", [], "confirmed")
    assert updated["entry"]["revision"] == 2


async def test_filters_apply_before_rank_limit_and_deleted_source_cannot_return(engine, tools):
    doc, _, entry = await saved(engine)
    for index in range(35):
        tools.store.put(
            "knowledge",
            {**entry, "id": f"archived-{index}", "status": "archived"},
            parent=doc,
            text="文献耦合 引用",
        )
    await tools.memory.update(entry["id"], 1, "已确认", ["引用"], "confirmed")
    found = tools.store.search("引用", "knowledge", status="confirmed", tag="引用", limit=1)
    assert [k["id"] for k in found] == [entry["id"]]
    tools.store.delete(doc)
    with pytest.raises(ValueError, match="来源文章已删除"):
        tools.store.put("knowledge", entry, parent=doc, text=entry["answer"], if_absent=True)
