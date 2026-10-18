import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from test_bibliometrics import install_openalex

from research_agent.api import create_app
from research_agent.config import PROJECT_ROOT


@pytest.mark.skipif(
    not shutil.which("node")
    or not Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists()
    or not (PROJECT_ROOT / "ppt/node_modules/playwright").exists(),
    reason="Local Chrome and Playwright are required",
)
def test_similarity_map_browser(engine, tools, monkeypatch):
    install_openalex(tools, monkeypatch)
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
                    str(PROJECT_ROOT / "scripts/verify_map_ui.cjs"),
                    f"http://127.0.0.1:{port}",
                    str(engine.settings.data_dir / "map.png"),
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
