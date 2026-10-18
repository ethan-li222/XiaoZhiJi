import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from research_agent.config import PROJECT_ROOT


@pytest.mark.skipif(
    not shutil.which("node")
    or not Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists(),
    reason="Local Node and Chrome required",
)
def test_real_browser_extracts_pages_and_google_keyup_search():
    arxiv = """<main><li class="arxiv-result"><p class="list-title"><a href="https://arxiv.org/abs/2401.12345">arXiv:2401.12345</a></p>
    <p class="title">Attention method</p><p class="authors"><a>Alice</a></p><p class="abstract-full">Verified abstract △ Less</p>
    <p>Submitted 12 January, 2024; originally announced January 2024.</p></li></main>"""
    google = """<div class="search-input"><input type="search"><button aria-label="Submit search">Search</button></div>
    <div id="results"><div class="row-card__container"><a class="row-card__heading">Unfiltered homepage</a></div></div>
    <script>let term='';document.querySelector('input').addEventListener('keyup',e=>term=e.target.value);
    document.querySelector('button').onclick=()=>{if(term==='attention')document.querySelector('#results').innerHTML=`
    <div class="row-card__container"><a class="row-card__heading" href="/detail">Attention paper</a>
    <span class="row-card__subheading__item">Bob</span><span class="row-card__subheading__item">Venue (2025)</span>
    <span class="glue-tooltip__body">A relevant abstract.</span></div>`;};</script>"""
    detail = """<meta name="citation_title" content="Attention paper"><meta name="citation_author" content="Bob">
    <meta name="citation_publication_date" content="2025"><a href="https://arxiv.org/pdf/2501.12345">Download</a>"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = detail if self.path == "/detail" else google if self.path == "/google" else arxiv
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        payload = {
            "query": "attention",
            "limit": 5,
            "site": "both",
            "sort": "relevance",
            "playwright_path": str(PROJECT_ROOT / "ppt/node_modules/playwright"),
            "test_urls": {"arxiv": origin + "/arxiv", "google_research": origin + "/google"},
        }
        result = subprocess.run(
            [shutil.which("node"), str(PROJECT_ROOT / "src/research_agent/browser_search.cjs")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
        )
        assert result.returncode == 0, result.stderr
        body = json.loads(result.stdout)
        assert all(p["status"] == "completed" for p in body["search_pages"]), body
        assert len(body["papers"]) == 2
        assert body["papers"][0]["published_at"].startswith("2024-01-12")
        assert body["papers"][0]["authors"] == ["Alice"]
        assert body["papers"][1]["title"] == "Attention paper"
        assert body["papers"][1]["pdf_url"] == "https://arxiv.org/pdf/2501.12345"
        assert body["papers"][1]["arxiv_id"] == "2501.12345"
        assert "Unfiltered homepage" not in str(body["papers"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
