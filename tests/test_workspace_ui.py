import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from pydantic import SecretStr

from research_agent.api import create_app
from research_agent.config import PROJECT_ROOT


@pytest.mark.skipif(
    not shutil.which("node")
    or not Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists(),
    reason="Chrome required",
)
def test_workspace_browser(engine):
    engine.settings.access_token = SecretStr("workspace-ui-test-" + "x" * 40)
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
                    str(PROJECT_ROOT / "scripts/verify_workspace_ui.cjs"),
                    f"http://127.0.0.1:{sock.getsockname()[1]}",
                    engine.settings.access_token.get_secret_value(),
                    str(engine.settings.data_dir / "research-desk.png"),
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
