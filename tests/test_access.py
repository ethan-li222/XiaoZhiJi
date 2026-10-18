from fastapi.testclient import TestClient
from pydantic import SecretStr

from research_agent.api import create_app


def test_private_access_and_upload(engine):
    engine.settings.access_token = SecretStr("private-test-token-" + "x" * 40)
    with TestClient(create_app(engine)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/tasks").status_code == 401
        assert client.get("/", follow_redirects=False).headers["location"] == "/login"
        assert client.post("/auth/login", json=[]).status_code == 422
        assert client.post("/auth/login", json={"token": "wrong"}).status_code == 401
        login = client.post(
            "/auth/login", json={"token": engine.settings.access_token.get_secret_value()}
        )
        assert login.status_code == 200
        assert "HttpOnly" in login.headers["set-cookie"]
        assert "SameSite=strict" in login.headers["set-cookie"]
        assert client.get("/workspace/state").status_code == 200
        assert (
            client.post("/workspace/uploads?filename=notes.md", content=b"notes").status_code == 403
        )
        origin = {"Origin": "http://testserver"}
        response = client.post(
            "/workspace/uploads?filename=../../notes.md", content=b"notes", headers=origin
        )
        assert response.status_code == 201
        from pathlib import Path

        assert Path(response.json()["source"]).parent == engine.settings.data_dir / "uploads"
        assert (
            client.post(
                "/workspace/uploads?filename=bad.pdf", content=b"bad", headers=origin
            ).status_code
            == 422
        )
        engine.settings.max_upload_bytes = 4
        assert (
            client.post(
                "/workspace/uploads?filename=a.md", content=b"12345", headers=origin
            ).status_code
            == 413
        )
        assert client.post("/auth/logout", json={}, headers=origin).status_code == 200
        assert client.get("/tasks").status_code == 401
        bearer = {"Authorization": "Bearer " + engine.settings.access_token.get_secret_value()}
        assert client.get("/tasks", headers=bearer).status_code == 200
        assert "frame-ancestors 'self'" in client.get("/health").headers["content-security-policy"]


def test_login_throttling_and_body_limit(engine):
    engine.settings.access_token = SecretStr("x" * 40)
    engine.settings.max_request_bytes = 100
    with TestClient(create_app(engine)) as client:
        assert client.post("/auth/login", content=b"x" * 101).status_code == 413
        for _ in range(8):
            assert client.post("/auth/login", json={"token": "bad"}).status_code == 401
        assert client.post("/auth/login", json={"token": "x" * 40}).status_code == 429
