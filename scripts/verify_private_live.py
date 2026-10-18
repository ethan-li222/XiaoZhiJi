"""Read-only smoke check of a running private deployment. Never prints its token."""

from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
with httpx.Client(base_url="http://127.0.0.1:8765", timeout=20) as client:
    assert client.get("/health").json()["status"] == "ok"
    required = client.get("/auth/status").json()["required"]
    assert client.get("/tasks").status_code == (401 if required else 200)
    if required:
        token = (root / "data/secrets/private-access.txt").read_text(encoding="utf-8").strip()
        assert client.post("/auth/login", json={"token": token}).status_code == 200
    state = client.get("/workspace/state")
    assert state.status_code == 200
    assert "metrics" in state.json()["stats"]
    assert client.get("/static/workspace.js").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["info"]["version"] == "0.2.0"
    assert "/workspace/uploads" in schema["paths"]
    assert (
        client.post(
            "/auth/logout", json={}, headers={"Origin": "http://127.0.0.1:8765"}
        ).status_code
        == 200
    )
    assert client.get("/tasks").status_code == (401 if required else 200)
    module = client.get("/pdfjs/build/pdf.mjs")
    assert module.status_code == 200 and "javascript" in module.headers["content-type"]
    assert client.get("/reader/library").status_code == 200
    memory = client.get("/memory/state")
    assert memory.status_code == 200 and "notebooks" in memory.json()
    assert client.get("/chat/sessions").status_code == 200
    assert "/chat/send" in schema["paths"]
print("Live access, workspace, PDF module MIME, reading library and configured auth mode passed")
