from datetime import timedelta

import pytest
from conftest import run
from fastapi.testclient import TestClient

from research_agent.api import create_app
from research_agent.mcp_client import Gateway
from research_agent.personal_memory import today


async def test_standalone_notes_are_searchable_exportable_and_versioned(engine, tools):
    result = await run(
        engine,
        "memory.note.save",
        {"text": "烹饪笔记：炖汤先焯水", "notebook": "生活技能", "tags": ["烹饪"]},
    )
    note = result["entry"]
    assert note["document_id"] is None
    assert not tools.store.list("document")
    assert note["event_date"] == today().isoformat()
    found = await run(engine, "memory.search", {"query": "炖汤"})
    assert note["id"] in {n["id"] for n in found["personal_entries"]}
    edited = await tools.call(
        "memory.note.save", {**note, "text": "炖汤控制盐量", "status": "confirmed"}
    )
    with pytest.raises(ValueError, match="刷新"):
        await tools.call("memory.note.save", {**note, "text": "旧版本"})
    exported = await run(engine, "memory.export", {})
    assert "生活技能" in exported["markdown"]
    await tools.call("memory.note.save", {**edited["entry"], "status": "archived"})
    found = await run(engine, "memory.search", {"query": "炖汤"})
    assert not found["personal_entries"]


async def test_repeat_operation_and_review_require_explicit_evidence(engine, tools):
    first = await tools.call("memory.note.save", {"text": "事件", "operation_id": "one"})
    second = await tools.call("memory.note.save", {"text": "事件", "operation_id": "one"})
    assert first["entry"]["id"] == second["entry"]["id"]
    sources = []
    for day in range(3):
        note = await tools.call(
            "memory.note.save",
            {
                "text": "先列清单再开始工作",
                "category": "event",
                "status": "confirmed",
                "tags": ["准备工作"],
                "event_date": (today() - timedelta(days=day)).isoformat(),
            },
        )
        sources.append(note["entry"]["id"])
    review = await run(engine, "memory.review", {"days": 7})
    assert review["personal_candidates"][0]["source_ids"] == sources
    assert not tools.store.list("personal_note")[-1]["layer"] == "behavior"
    promoted = await tools.call(
        "memory.note.save", {**review["personal_candidates"][0], "origin": "review"}
    )
    assert promoted["entry"]["status"] == "inbox"
    with pytest.raises(ValueError, match="三个不同日期"):
        await tools.call(
            "memory.note.save",
            {"text": "候选", "layer": "behavior", "origin": "review", "source_ids": sources[:2]},
        )
    with pytest.raises(ValueError, match="核心层"):
        await tools.call(
            "memory.note.save",
            {"text": "自动价值观", "layer": "core", "origin": "review", "source_ids": sources},
        )
    manual = await tools.call(
        "memory.note.save", {"text": "我重视诚实", "layer": "core", "category": "value"}
    )
    assert manual["entry"]["origin"] == "manual"


async def test_same_day_records_do_not_create_behavior_candidate(engine):
    for _ in range(4):
        await run(
            engine,
            "memory.note.save",
            {"text": "同日记录", "category": "event", "status": "confirmed", "tags": ["同一天"]},
        )
    assert not (await run(engine, "memory.review", {}))["personal_candidates"]


async def test_reader_note_checks_quote_and_retains_broken_source(engine, tools):
    document = (
        await run(
            engine,
            "documents.import",
            {"source": "test", "text": "Personal knowledge may come from daily life."},
        )
    )["document"]
    note = (
        await run(
            engine,
            "memory.note.save",
            {
                "text": "不只科研",
                "document_id": document["id"],
                "selection": "Personal knowledge",
                "status": "confirmed",
            },
        )
    )["entry"]
    with pytest.raises(ValueError, match="未在原文"):
        await tools.call(
            "memory.note.save",
            {"text": "伪选段", "document_id": document["id"], "selection": "invented quote"},
        )
    await run(engine, "documents.delete", {"id": document["id"]})
    assert tools.store.get(note["id"], "personal_note")
    with TestClient(create_app(engine)) as client:
        assert client.get("/memory/state").json()["notes"][0]["missing_sources"] == [document["id"]]
    saved = await tools.call("memory.note.save", {**note, "text": "来源已失效，保留个人理解"})
    assert saved["entry"]["revision"] == 2


async def test_personal_reading_notes_join_research_only_after_confirmation(engine, tools):
    project = (await run(engine, "workspace.project.save", {"name": "阅读项目"}))["entry"]
    material = await run(
        engine,
        "workspace.import",
        {"project_id": project["id"], "source": "note", "text": "检索需要基线。"},
    )
    note = (
        await run(
            engine,
            "memory.note.save",
            {"text": "固定基线", "document_id": material["document"]["id"]},
        )
    )["entry"]
    with pytest.raises(ValueError, match="已确认"):
        tools.workspace.source(note["id"], project["id"])
    await tools.call("memory.note.save", {**note, "status": "confirmed"})
    assert tools.workspace.source(note["id"], project["id"])["kind"] == "personal_note"
    synthesis = await run(engine, "workspace.synthesize", {"project_id": project["id"]})
    assert synthesis["sources"][0]["id"] == note["id"]


async def test_personal_memory_real_stdio(settings):
    settings.tool_transport = "stdio"
    async with Gateway(settings).open() as gateway:
        result = await gateway.call(
            "memory.note.save",
            {"text": "每周整理生活收支", "notebook": "生活", "event_date": today().isoformat()},
        )
        assert result["entry"]["document_id"] is None
        found = await gateway.call("memory.search", {"query": "生活收支"})
        assert result["entry"]["id"] in {n["id"] for n in found["personal_entries"]}
        exported = await gateway.call("memory.export", {})
        assert "每周整理生活收支" in exported["markdown"]
