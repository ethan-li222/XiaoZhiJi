import io
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from research_agent.config import PROJECT_ROOT
from research_agent.embedding import Embedder
from research_agent.models import Paper
from research_agent.papers import deduplicate


def pdf_bytes():
    writer = PdfWriter()
    for text in ("Bibliographic coupling", "Co-citation on second page"):
        page = writer.add_blank_page(width=500, height=500)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 40 400 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()


async def test_pdf_url_and_page_location(tools):
    data = pdf_bytes()
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=data, headers={"Content-Type": "application/pdf"})
        )
    )
    result = await tools.documents.import_document("https://example.org/article")
    assert result["document"]["chunks"] == 2
    evidence = await tools.documents.retrieve(result["document"]["id"], "co-citation", page=2)
    assert len(evidence["evidence"]) == 1
    assert evidence["evidence"][0]["page"] == 2
    assert "second page" in evidence["evidence"][0]["text"]
    assert await tools.net.get("https://example.org/article", binary=True) == data


def test_transitive_deduplication():
    papers = deduplicate(
        [
            Paper(id="oa", title="A", doi="10.1/a"),
            Paper(id="arxiv", title="A", arxiv_id="2005.11401"),
            Paper(
                id="s2", title="A", doi="10.1/a", arxiv_id="2005.11401", abstract="Full abstract"
            ),
        ]
    )
    assert len(papers) == 1
    assert papers[0].id == "oa"
    assert papers[0].arxiv_id == "2005.11401"
    assert papers[0].abstract == "Full abstract"


@pytest.mark.parametrize("total", [3, 10])
async def test_openalex_citation_offset_remainder(tools, monkeypatch, total):
    seed = Paper(
        id="https://openalex.org/W1",
        title="Seed",
        source_ids={"openalex": "https://openalex.org/W1"},
    )
    tools.store.put("paper", seed.model_dump())

    async def oa(suffix="", params=None):
        if suffix:
            return {"referenced_works": []}
        page = params["page"]
        return {
            "results": [
                {"id": f"https://openalex.org/W{i}", "title": str(i)}
                for i in range(10 + (page - 1) * 2, 12 + (page - 1) * 2)
            ],
            "meta": {"count": total},
        }

    monkeypatch.setattr(tools.papers, "oa", oa)
    result = await tools.papers.related(seed.id, limit=2, offset=1, similar_limit=0)
    assert {r["source"] for r in result["relations"]} == {
        "https://openalex.org/W11",
        "https://openalex.org/W12",
    }


@pytest.mark.skipif(
    not (PROJECT_ROOT / "data/embedding-model/modules.json").exists(),
    reason="run embeddings init first",
)
async def test_real_multilingual_embedding_and_hybrid_retrieval(tools, settings):
    settings.embedding_dir = PROJECT_ROOT / "data/embedding-model"
    tools.documents.embedder = Embedder(settings)
    result = await tools.documents.import_document(
        "real-model",
        text="# 科研\n\n两篇论文共享参考文献，这是文献耦合。\n\n# 厨房\n\n面包烘烤时需要控制温度。",
    )
    assert result["warnings"] == []
    found = await tools.documents.retrieve(
        result["document"]["id"], "bibliographic coupling shared references"
    )
    assert "耦合" in found["evidence"][0]["text"]
    assert found["warnings"] == []


@pytest.mark.skipif(
    not Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists()
    or not (PROJECT_ROOT / "ppt/node_modules/@playwright/mcp/cli.js").exists(),
    reason="Chrome and Playwright MCP required",
)
async def test_real_headless_chrome_context(settings, tools, monkeypatch):
    # Playwright's pinned server registry supports an isolated test directory.
    monkeypatch.setenv("PWTEST_SERVER_REGISTRY", str(settings.data_dir / "browser-registry"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                '<html><head><title>科研阅读</title></head><body><main id="article"></main><script>document.querySelector("main").textContent="Chrome 动态科研正文"</script></body></html>'.encode()
            )

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = await tools.documents.browser_text(f"http://127.0.0.1:{server.server_port}/")
        assert result["title"] == "科研阅读"
        assert result["text"] == "Chrome 动态科研正文"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
