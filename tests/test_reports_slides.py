import json
import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from conftest import run

from research_agent.config import PROJECT_ROOT
from research_agent.models import Source
from research_agent.reports import filter_sources


def test_report_window_duplicates_unknown_and_future():
    clock = datetime(2026, 10, 5, tzinfo=UTC)
    sources = [
        Source(
            id="new",
            title="graph",
            url="https://example.org/new",
            text="",
            published_at=(clock - timedelta(days=1)).isoformat(),
        ),
        Source(
            id="duplicate",
            title="graph",
            url="https://example.org/new/",
            text="",
            published_at=clock.isoformat(),
        ),
        Source(
            id="old",
            title="graph",
            url="https://example.org/old",
            text="",
            published_at=(clock - timedelta(days=20)).isoformat(),
        ),
        Source(
            id="future",
            title="graph",
            url="https://example.org/future",
            text="",
            published_at=(clock + timedelta(days=1)).isoformat(),
        ),
        Source(id="unknown", title="graph", url="https://example.org/unknown", text=""),
        Source(
            id="unrelated",
            title="other",
            url="https://example.org/other",
            text="",
            published_at=clock.isoformat(),
        ),
    ]
    kept, unknown = filter_sources(sources, 7, "graph", clock)
    assert [s.id for s in kept] == ["new"]
    assert [s.id for s in unknown] == ["unknown"]


async def test_industry_report_sources_and_invalid_citations(engine, tools, model):
    date = datetime.now(UTC).isoformat()
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "Graph release",
                        "tag_name": "v1",
                        "html_url": "https://github.com/test/test/releases/1",
                        "body": "Graph improvements",
                        "published_at": date,
                    }
                ],
            )
        )
    )
    params = {
        "topic": "Graph",
        "kind": "industry",
        "sources": [{"type": "github", "repo": "test/test"}],
    }
    model.invalid = True
    task = engine.create("reports.generate", params)
    assert (await engine.run(task["id"]))["status"] == "failed"
    model.invalid = False
    result = (await engine.run(task["id"], resume=True))["result"]
    assert result["report"]["sections"][0]["source_ids"] == ["release-1"]
    markdown = Path(result["artifacts"]["markdown"]).read_text(encoding="utf-8")
    assert "https://github.com/test/test/releases/1" in markdown


async def test_empty_report_skips_model(engine, tools, model):
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    )
    result = await run(
        engine,
        "reports.generate",
        {
            "topic": "graph",
            "kind": "industry",
            "sources": [{"type": "github", "repo": "test/test"}],
        },
    )
    assert result["report"]["sections"] == []
    assert result["report"]["warnings"]
    assert model.calls == []


async def test_research_query_bounds_dates_before_limiting(tools):
    from test_papers import oa

    now = datetime.now(UTC)
    recent = oa()
    recent["publication_date"] = (now - timedelta(days=1)).date().isoformat()
    recent["publication_year"] = now.year
    seen_arxiv = []

    def handler(request):
        if "openalex" in request.url.host:
            filters = request.url.params["filter"]
            assert f"to_publication_date:{now.date().isoformat()}" in filters
            assert (
                f"from_publication_date:{(now - timedelta(days=7)).date().isoformat()}" in filters
            )
            return httpx.Response(200, json={"results": [recent]})
        seen_arxiv.append(request.url.params["search_query"])
        return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"/>')

    tools.net.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    report = await tools.reports.collect("Graph", limit=1)
    assert len(report["sources"]) == 1
    assert "submittedDate:[" in seen_arxiv[0]


async def test_rss_source_failure_and_unknown_date(tools):
    xml = '<rss version="2.0"><channel><title>Blog</title><item><title>Graph</title><link>https://example.org/x</link><description>Graph release</description></item></channel></rss>'
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(403) if "fail" in str(r.url) else httpx.Response(200, text=xml)
        )
    )
    result = await tools.reports.collect(
        "Graph",
        "industry",
        sources=[
            {"type": "rss", "url": "https://example.org/feed"},
            {"type": "rss", "url": "https://example.org/fail"},
        ],
    )
    assert not result["sources"]
    assert len(result["unknown_date_sources"]) == 1
    assert result["warnings"]


async def test_outline_revision_preserves_other_slides(engine, tmp_path):
    material = tmp_path / "report.md"
    material.write_text("科研报告素材", encoding="utf-8")
    outline = await run(engine, "slides.outline", {"source": str(material), "pages": 3})
    deck = outline["deck"]
    revised = await run(
        engine, "slides.revise", {"deck": deck, "page": 2, "instruction": "减少文字"}
    )
    assert revised["deck"]["slides"][0] == deck["slides"][0]
    assert revised["deck"]["slides"][2] == deck["slides"][2]
    assert revised["deck"]["slides"][1]["title"] == "已修改"
    assert not revised["confirmed"]


async def test_automatic_outline_rejects_unconfirmed_chart(engine, model, tmp_path):
    material = tmp_path / "report.md"
    material.write_text("只提供定性说明，未提供统计数字。", encoding="utf-8")
    original_generate = model.generate

    async def invented_chart(instruction, payload, schema):
        deck = await original_generate(instruction, payload, schema)
        from research_agent.models import ChartSeries

        deck.slides[0].chart = [ChartSeries(name="主观评分", labels=["效率"], values=[9])]
        return deck

    model.generate = invented_chart
    task = engine.create("slides.outline", {"source": str(material), "pages": 1})
    result = await engine.run(task["id"])
    assert result["status"] == "failed"
    assert "未经确认" in result["error"]


@pytest.mark.skipif(
    not shutil.which("node") or not (PROJECT_ROOT / "ppt/node_modules/pptxgenjs").exists(),
    reason="npm ci --prefix ppt required",
)
async def test_real_pptx_chinese_tables_chart_and_long_text(engine):
    deck = json.loads((PROJECT_ROOT / "examples/deck.json").read_text(encoding="utf-8"))
    deck["slides"][0]["bullets"].append("长文字分页验证" * 200)
    result = await run(engine, "slides.build", {"deck": deck})
    with zipfile.ZipFile(result["pptx"]) as pptx:
        assert pptx.testzip() is None
        files = pptx.namelist()
        assert "ppt/charts/chart1.xml" in files
        slides = [p for p in files if p.startswith("ppt/slides/slide") and p.endswith(".xml")]
        assert len(slides) > 6
        all_xml = "".join(pptx.read(p).decode() for p in slides)
        assert "论文" in all_xml
        assert "<a:tbl>" in all_xml


def test_invalid_chart_and_source():
    from research_agent.models import SlideDeck
    from research_agent.slides import validate_deck

    with pytest.raises(ValueError, match="来源"):
        validate_deck(SlideDeck(title="bad", slides=[{"title": "x", "source_ids": ["missing"]}]))
    with pytest.raises(ValueError, match="对齐"):
        validate_deck(
            SlideDeck(
                title="bad",
                slides=[{"title": "x", "chart": [{"name": "x", "labels": ["a"], "values": []}]}],
            )
        )
