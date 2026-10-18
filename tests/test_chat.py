import asyncio
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from conftest import run
from fastapi.testclient import TestClient

from research_agent.api import create_app
from research_agent.chat import new_session
from research_agent.config import PROJECT_ROOT
from research_agent.mcp_client import Gateway


def session(engine):
    return engine.store.put("chat_session", new_session())


async def test_chat_history_does_not_implicitly_read_memory(engine, model):
    await run(
        engine,
        "memory.note.save",
        {"text": "我的私人价值观", "layer": "core", "status": "confirmed"},
    )
    chat = session(engine)
    first = await run(
        engine, "chat.send", {"session_id": chat["id"], "revision": 1, "message": "帮我制定计划"}
    )
    assert first["revision"] == 2
    assert model.calls[-1]["sources"] == []
    second = await run(
        engine, "chat.send", {"session_id": chat["id"], "revision": 2, "message": "再详细一点"}
    )
    assert second["revision"] == 3
    assert model.calls[-1]["history"][0]["user"] == "帮我制定计划"
    assert len(engine.store.get(chat["id"], "chat_session")["turns"]) == 2


async def test_chat_scopes_citations_and_stale_revision(engine, model, tools):
    note = (
        await run(engine, "memory.note.save", {"text": "学习先制定计划", "status": "confirmed"})
    )["entry"]
    core = (
        await run(
            engine,
            "memory.note.save",
            {"text": "我看重长期成长", "layer": "core", "status": "confirmed"},
        )
    )["entry"]
    chat = session(engine)
    await run(
        engine,
        "chat.send",
        {"session_id": chat["id"], "revision": 1, "message": "计划", "scope": "knowledge"},
    )
    assert note["id"] in {s["id"] for s in model.calls[-1]["sources"]}
    assert core["id"] not in {s["id"] for s in model.calls[-1]["sources"]}
    await run(
        engine,
        "chat.send",
        {"session_id": chat["id"], "revision": 2, "message": "长期成长", "scope": "personal"},
    )
    assert core["id"] in {s["id"] for s in model.calls[-1]["sources"]}
    with pytest.raises(ValueError, match="已更新"):
        await tools.call(
            "chat.send", {"session_id": chat["id"], "revision": 1, "message": "过期消息"}
        )
    model.invalid = True
    task = engine.create(
        "chat.send", {"session_id": chat["id"], "revision": 3, "message": "无效引用"}
    )
    assert (await engine.run(task["id"]))["status"] == "failed"
    assert len(engine.store.get(chat["id"], "chat_session")["turns"]) == 2
    model.invalid = False
    result = await engine.run(task["id"], resume=True)
    assert result["status"] == "completed"
    assert len(engine.store.get(chat["id"], "chat_session")["turns"]) == 3


async def test_chat_document_context_and_retry_idempotency(engine, tools):
    doc = (
        await run(engine, "documents.import", {"source": "chat-test", "text": "检索需要实验验证。"})
    )["document"]
    chat = session(engine)
    task = engine.create(
        "chat.send",
        {"session_id": chat["id"], "revision": 1, "message": "解释检索", "document_id": doc["id"]},
    )
    completed = await engine.run(task["id"])
    assert completed["result"]["sources"][0]["record_id"] == doc["id"]
    replay = await tools.call("chat.send", {**task["params"], "operation_id": task["id"]})
    assert replay["completed_turn"]["task_id"] == task["id"]
    with TestClient(create_app(engine)) as client:
        assert client.get("/chat/sessions").json()[0]["turn_count"] == 1
        assert client.delete("/chat/sessions/" + chat["id"]).status_code == 200
        assert client.get("/chat/sessions/" + chat["id"]).status_code == 404


async def test_actual_chat_context_stdio(settings):
    from research_agent.storage import Store

    settings.tool_transport = "stdio"
    chat = Store(settings.data_dir).put("chat_session", new_session())
    async with Gateway(settings).open() as gateway:
        result = await gateway.call(
            "chat.send", {"session_id": chat["id"], "revision": 1, "message": "你好"}
        )
        assert result["sources"] == [] and result["message"] == "你好"


async def test_chat_multiple_documents_and_project_boundaries(engine, model, tools):
    docs = []
    for name in ("project-a", "project-b", "outside"):
        docs.append(
            (
                await run(
                    engine,
                    "documents.import",
                    {
                        "source": name,
                        "text": name + " retrieval experiment evidence",
                        "title": name,
                    },
                )
            )["document"]
        )
    project = engine.store.put(
        "project",
        {
            "id": "project-context",
            "name": "Context project",
            "question": "retrieval",
            "next_step": "experiment",
        },
    )
    for index, doc in enumerate(docs[:2]):
        engine.store.put(
            "library", {"id": f"lib-{index}", "project_id": project["id"], "document_id": doc["id"]}
        )
    chat = session(engine)
    base = {
        "session_id": chat["id"],
        "revision": 1,
        "message": "retrieval",
        "project_id": project["id"],
    }
    context = await tools.call("chat.send", base)
    assert {s["record_id"] for s in context["sources"] if s["kind"] == "chunk"} == {
        d["id"] for d in docs[:2]
    }
    empty = await tools.call("chat.send", {**base, "document_mode": "selected"})
    assert not any(s["kind"] == "chunk" for s in empty["sources"])
    selected = [docs[0]["id"], docs[2]["id"]]
    await run(engine, "chat.send", {**base, "document_ids": selected})
    assert {s["record_id"] for s in model.calls[-1]["sources"] if s["kind"] == "chunk"} == set(
        selected
    )
    assert engine.store.get(chat["id"], "chat_session")["turns"][0]["document_ids"] == selected
    with pytest.raises(ValueError):
        await tools.call("chat.send", {**base, "revision": 2, "document_ids": ["missing-document"]})
    with pytest.raises(ValueError):
        engine.create("chat.send", {**base, "document_ids": [str(i) for i in range(7)]})


def test_api_rejects_overlapping_chat_turns(engine, model, monkeypatch):
    original = model.generate

    async def slow(instruction, payload, schema):
        await asyncio.sleep(0.25)
        return await original(instruction, payload, schema)

    monkeypatch.setattr(model, "generate", slow)
    with TestClient(create_app(engine)) as client:
        chat = client.post("/chat/sessions").json()
        body = {
            "action": "chat.send",
            "params": {"session_id": chat["id"], "revision": 1, "message": "先回答这条"},
        }
        first = client.post("/tasks", json=body)
        assert first.status_code == 202
        assert client.post("/tasks", json=body).status_code == 409
        for _ in range(100):
            state = client.get("/tasks/" + first.json()["task_id"]).json()
            if state["status"] == "completed":
                break
            time.sleep(0.02)
        assert state["status"] == "completed"
        assert len(client.get("/chat/sessions/" + chat["id"]).json()["turns"]) == 1


@pytest.mark.skipif(
    not shutil.which("node")
    or not Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists(),
    reason="Chrome required",
)
def test_chat_browser(engine):
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
                    str(PROJECT_ROOT / "scripts/verify_chat_ui.cjs"),
                    f"http://127.0.0.1:{sock.getsockname()[1]}",
                    str(engine.settings.data_dir / "chat.png"),
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
