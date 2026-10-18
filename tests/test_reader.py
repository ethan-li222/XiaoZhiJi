import hashlib
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient
from test_boundaries import pdf_bytes

from research_agent.api import create_app
from research_agent.config import PROJECT_ROOT
from research_agent.mcp_client import Gateway
from research_agent.models import Paper


def cached_paper(engine):
    paper = Paper(id="cached-paper", title="Downloaded paper", pdf_url="https://example.org/p.pdf")
    engine.store.put("paper", paper.model_dump())
    directory = engine.settings.data_dir / "paper-downloads"
    directory.mkdir()
    path = directory / (hashlib.sha256(paper.id.encode()).hexdigest()[:24] + ".pdf")
    path.write_bytes(pdf_bytes())
    return paper


async def test_cached_pdf_opens_without_download_and_is_archived(engine, tools):
    paper = cached_paper(engine)
    first = await tools.call("documents.open", {"paper_id": paper.id})
    second = await tools.call("documents.open", {"paper_id": paper.id})
    assert first["document"]["id"] == second["document"]["id"]
    assert Path(first["document"]["pdf_path"]).is_file()
    assert len(engine.store.list("document")) == 1
    engine.settings.tool_transport = "stdio"
    async with Gateway(engine.settings).open() as gateway:
        remote = await gateway.call("documents.open", {"paper_id": paper.id})
        assert remote["document"]["id"] == first["document"]["id"]
    with TestClient(create_app(engine)) as client:
        assert client.get("/auth/status").json()["required"] is False
        assert client.get("/reader/library").json()["downloaded"] == []
        item = client.get("/reader/documents/" + first["document"]["id"]).json()
        assert client.get(item["pdf_url"]).content.startswith(b"%PDF")
        broken = {
            **first["document"],
            "pdf_path": str(engine.settings.data_dir / "research.sqlite3"),
        }
        engine.store.put("document", broken)
        assert client.get(item["pdf_url"]).status_code == 404


@pytest.mark.skipif(
    not shutil.which("node")
    or not Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists(),
    reason="Chrome required",
)
def test_reader_pdf_text_selection_ask_and_save(engine):
    cached_paper(engine)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
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
                    str(PROJECT_ROOT / "scripts/verify_reader_ui.cjs"),
                    f"http://127.0.0.1:{sock.getsockname()[1]}",
                    str(engine.settings.data_dir / "reader.png"),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            server.should_exit = True
            thread.join(timeout=10)
