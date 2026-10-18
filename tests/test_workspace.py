from datetime import UTC
from pathlib import Path

import httpx
import pytest
from conftest import run
from test_boundaries import pdf_bytes

from research_agent.models import Paper


async def setup_project(engine):
    project = (
        await run(
            engine, "workspace.project.save", {"name": "检索研究", "question": "如何提高检索可靠性"}
        )
    )["entry"]
    material = await run(
        engine,
        "workspace.import",
        {
            "project_id": project["id"],
            "source": "https://openai.com/example",
            "text": "# 检索\n\n检索质量需要用实际数据和基线验证。",
            "title": "工程实践",
            "kind": "industry",
            "organization": "OpenAI",
        },
    )
    annotation = (
        await run(
            engine,
            "workspace.annotation.save",
            {
                "project_id": project["id"],
                "document_id": material["document"]["id"],
                "selection": "检索质量需要用实际数据和基线验证。",
                "kind": "industry",
                "text": "需要区分模型变化和检索变化的影响。",
            },
        )
    )["entry"]
    return project, material["entry"], annotation


async def test_project_notes_idea_experiment_weekly_and_ppt(engine, tools):
    project, material, annotation = await setup_project(engine)
    assert material["source_status"] == "official_domain"
    idea = (
        await run(
            engine,
            "workspace.idea.save",
            {
                "project_id": project["id"],
                "title": "控制检索变量",
                "hypothesis": "固定生成器能隔离检索影响",
                "source_ids": [annotation["id"]],
                "status": "ready",
            },
        )
    )["entry"]
    exp = (
        await run(
            engine,
            "workspace.experiment.save",
            {
                "idea_id": idea["id"],
                "title": "检索对照",
                "baseline": "固定检索器",
                "dataset": "验证集",
                "metrics": "准确率",
                "expected_result": "可能改善",
            },
        )
    )["entry"]
    assert exp["actual_result"] == "" and exp["status"] == "designed"
    await run(
        engine,
        "workspace.reading.log",
        {"id": material["id"], "minutes": 25, "reflection": "记录局限"},
    )
    await run(
        engine,
        "workspace.library.update",
        {
            "id": material["id"],
            "revision": material["revision"],
            "status": "read",
            "tags": ["检索"],
        },
    )
    weekly = await run(engine, "workspace.weekly", {"project_id": project["id"], "days": 7})
    assert weekly["stats"]["metrics"]["self_reported_minutes"] == 25
    assert weekly["stats"]["metrics"]["reading_completions"] == 1
    assert "未记录结果" in weekly["markdown"]
    assert len(weekly["deck"]["slides"]) == 6
    built = await run(engine, "slides.build", {"deck": weekly["deck"]})
    assert Path(built["pptx"]).is_file()
    assert not tools.store.list("knowledge")


async def test_acquire_classifies_pdf_and_reuses_document(engine, tools):
    project = (await run(engine, "workspace.project.save", {"name": "论文分类"}))["entry"]
    tools.store.put(
        "paper",
        Paper(
            id="p", title="Bibliographic coupling", year=2025, pdf_url="https://example.org/p.pdf"
        ).model_dump(),
    )
    item = (
        await run(engine, "workspace.library.add", {"project_id": project["id"], "paper_id": "p"})
    )["entry"]
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=pdf_bytes()))
    )
    acquired = await run(engine, "workspace.library.acquire", {"id": item["id"]})
    assert Path(acquired["entry"]["pdf_path"]).is_relative_to(
        tools.settings.data_dir / "library" / project["id"]
    )
    assert acquired["entry"]["document_id"] == acquired["document"]["id"]
    again = await run(engine, "workspace.library.acquire", {"id": item["id"]})
    assert again["document"]["id"] == acquired["document"]["id"]
    assert len(tools.store.list("document")) == 1


async def test_invalid_quote_cross_project_and_stale_version(engine, tools):
    project, material, annotation = await setup_project(engine)
    invalid = engine.create(
        "workspace.annotation.save",
        {
            "project_id": project["id"],
            "document_id": material["document_id"],
            "selection": "伪造的原文",
            "text": "注释",
        },
    )
    assert (await engine.run(invalid["id"]))["status"] == "failed"
    other = (await run(engine, "workspace.project.save", {"name": "另一个项目"}))["entry"]
    with pytest.raises(ValueError, match="另一个项目"):
        await tools.call(
            "workspace.idea.save",
            {
                "project_id": other["id"],
                "title": "越界",
                "hypothesis": "假设",
                "source_ids": [annotation["id"]],
            },
        )
    await tools.call("workspace.project.save", {**project, "name": "新名称"})
    with pytest.raises(ValueError, match="刷新"):
        await tools.call("workspace.project.save", {**project, "name": "过期名称"})


async def test_operation_retry_does_not_duplicate_records_or_minutes(engine, tools):
    _, material, _ = await setup_project(engine)
    params = {"id": material["id"], "minutes": 20, "operation_id": "fixed-operation"}
    first = await tools.call("workspace.reading.log", params)
    second = await tools.call("workspace.reading.log", params)
    assert first["entry"]["id"] == second["entry"]["id"]
    assert len(tools.store.list("reading_log")) == 1


async def test_synthesis_rejects_hallucinated_sources_and_coach_skips_small_sample(engine, model):
    project, _, _ = await setup_project(engine)
    result = await run(engine, "workspace.synthesize", {"project_id": project["id"]})
    assert result["synthesis"]["candidate_ideas"]
    model.invalid = True
    task = engine.create("workspace.synthesize", {"project_id": project["id"]})
    assert (await engine.run(task["id"]))["status"] == "failed"
    model.invalid = False
    previous = len(model.calls)
    coach = await run(engine, "workspace.coach", {"project_id": project["id"], "days": 28})
    assert "覆盖不足" in coach["message"]
    assert len(model.calls) == previous


async def test_deleted_source_is_not_used_in_synthesis(engine, tools):
    project, material, annotation = await setup_project(engine)
    await run(
        engine,
        "workspace.idea.save",
        {
            "project_id": project["id"],
            "title": "假设",
            "hypothesis": "待验证",
            "source_ids": [annotation["id"]],
        },
    )
    await run(engine, "documents.delete", {"id": material["document_id"]})
    result = await run(engine, "workspace.synthesize", {"project_id": project["id"]})
    assert not result["sources"]
    assert "没有可用笔记" in result["message"]


async def test_local_pdf_import_archives_and_retry_keeps_metadata(engine, tools):
    project = (await run(engine, "workspace.project.save", {"name": "上传论文"}))["entry"]
    source = tools.settings.data_dir / "upload.pdf"
    source.write_bytes(pdf_bytes())
    params = {
        "project_id": project["id"],
        "source": str(source),
        "kind": "paper",
        "operation_id": "upload-once",
    }
    first = await tools.call("workspace.import", params)
    assert Path(first["entry"]["pdf_path"]).is_file()
    second = await tools.call("workspace.import", params)
    assert second["entry"] == first["entry"]
    assert len(tools.store.list("document")) == 1


async def test_coach_uses_recorded_dates_and_validates_metric_keys(engine, tools, model):
    from datetime import datetime, timedelta

    project, material, _ = await setup_project(engine)
    for day in range(7):
        record = (await tools.call("workspace.reading.log", {"id": material["id"], "minutes": 25}))[
            "entry"
        ]
        record["created_at"] = (datetime.now(UTC) - timedelta(days=day)).isoformat()
        tools.store.put("reading_log", record, parent=material["id"])
    stats = await run(engine, "workspace.stats", {"project_id": project["id"], "days": 28})
    assert stats["metrics"]["recorded_reading_days"] == 7
    assert stats["metrics"]["self_reported_minutes"] == 175
    assert stats["eligible_for_coaching"]
    advice = await run(engine, "workspace.coach", {"project_id": project["id"], "days": 28})
    assert advice["advice"]["observations"]
    model.invalid = True
    task = engine.create("workspace.coach", {"project_id": project["id"], "days": 28})
    assert (await engine.run(task["id"]))["status"] == "failed"
