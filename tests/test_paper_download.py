import httpx
import pytest
from conftest import run
from test_boundaries import pdf_bytes

from research_agent.models import Paper
from research_agent.papers import from_semantic


async def test_pdf_download_creates_artifact_without_knowledge(engine, tools):
    from pathlib import Path

    tools.store.put(
        "paper", Paper(id="p", title="Paper", pdf_url="https://example.org/p.pdf").model_dump()
    )
    raw = pdf_bytes()
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=raw))
    )
    result = await run(engine, "papers.download", {"paper_id": "p"})
    assert Path(result["artifacts"]["pdf"]).read_bytes() == raw
    assert not tools.store.list("knowledge")
    assert not tools.store.list("document")


async def test_download_missing_url_or_non_pdf(tools):
    tools.store.put("paper", Paper(id="missing", title="Missing").model_dump())
    with pytest.raises(ValueError, match="开放 PDF"):
        await tools.papers.download("missing")
    tools.store.put(
        "paper", Paper(id="html", title="Login", pdf_url="https://example.org/login").model_dump()
    )
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>login</html>"))
    )
    with pytest.raises(ValueError, match="未返回 PDF"):
        await tools.papers.download("html")
    assert not (tools.settings.data_dir / "paper-downloads").exists()


async def test_directional_pagination_and_open_pdf_metadata(tools, monkeypatch):
    tools.store.put(
        "paper", Paper(id="S2:seed", title="Seed", source_ids={"semantic": "seed"}).model_dump()
    )
    calls = []

    async def s2(suffix, params):
        calls.append((suffix, params))
        return {
            "data": [
                {
                    "citingPaper": {
                        "paperId": "next",
                        "title": "Next",
                        "openAccessPdf": {"url": "https://example.org/next.pdf"},
                    }
                }
            ]
        }

    monkeypatch.setattr(tools.papers, "s2", s2)
    result = await tools.call(
        "papers.related",
        {
            "seed": "S2:seed",
            "direction": "citations",
            "offset": 20,
            "limit": 20,
            "similar_limit": 0,
        },
    )
    assert len(calls) == 1
    assert calls[0][0].endswith("citations") and calls[0][1]["offset"] == 20
    assert "openAccessPdf" in calls[0][1]["fields"]
    assert result["relations"][0]["source"] == "S2:next"
    assert result["papers"][1]["pdf_url"] == "https://example.org/next.pdf"


def test_semantic_pdf_mapping():
    paper = from_semantic({"paperId": "a", "openAccessPdf": {"url": "https://example.org/a.pdf"}})
    assert paper.pdf_url.endswith("a.pdf")
