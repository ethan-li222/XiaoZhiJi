import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from test_boundaries import pdf_bytes

from research_agent.api import create_app
from research_agent.config import PROJECT_ROOT
from research_agent.models import Paper


@pytest.mark.skipif(
    not shutil.which("node")
    or not Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists()
    or not (PROJECT_ROOT / "ppt/node_modules/playwright").exists(),
    reason="Local Chrome and Playwright are required",
)
def test_paper_browser_workflow(engine, tools):
    tools.store.put(
        "paper",
        Paper(
            id="S2:seed", title="Seed", citation_count=120, source_ids={"semantic": "seed"}
        ).model_dump(),
    )

    def handler(request):
        if request.url.host == "example.org":
            return httpx.Response(200, content=pdf_bytes())
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/W9",
                            "title": "Search PDF",
                            "best_oa_location": {"pdf_url": "https://example.org/9.pdf"},
                        },
                        {"id": "https://openalex.org/W10", "title": "No PDF"},
                    ]
                },
            )
        if request.url.host == "export.arxiv.org":
            return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"/>')
        if request.url.path.endswith("references"):
            return httpx.Response(
                200, json={"data": [{"citedPaper": {"paperId": "ref", "title": "Reference"}}]}
            )
        next_page = int(request.url.params.get("offset", 0)) > 0
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "citingPaper": {
                            "paperId": "next" if next_page else "citing",
                            "title": "Next" if next_page else "Citation",
                            "openAccessPdf": {"url": "https://example.org/p.pdf"},
                        }
                    }
                ],
                "next": None if next_page else 10,
            },
        )

    tools.net.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def browser(*args):
        return {
            "papers": [
                Paper(
                    id="arxiv:2401.12345",
                    title="Browser search result",
                    arxiv_id="2401.12345",
                    pdf_url="https://example.org/browser.pdf",
                    source_ids={"arxiv": "2401.12345", "browser": "arxiv"},
                ).model_dump()
            ],
            "transport": "browser",
            "search_pages": [
                {
                    "site": "arxiv",
                    "status": "completed",
                    "count": 1,
                    "url": "https://arxiv.org/search/",
                }
            ],
            "warnings": [],
        }

    tools.papers.browser.search = browser
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(engine), log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.02)
            assert server.started
            result = subprocess.run(
                [
                    shutil.which("node"),
                    str(PROJECT_ROOT / "scripts/verify_papers_ui.cjs"),
                    f"http://127.0.0.1:{port}",
                    str(engine.settings.data_dir / "graph.png"),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
            )
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            server.should_exit = True
            thread.join(timeout=10)
