import time

import pytest
from fastapi.testclient import TestClient

from research_agent.api import create_app
from research_agent.mcp_client import Gateway


def test_api_tasks_resources_validation_and_artifacts(engine):
    with TestClient(create_app(engine)) as client:
        assert "小知己" in client.get("/").text
        assert client.get("/static/app.js").status_code == 200
        info = client.get("/info").json()
        assert set(info) == {"application", "model", "model_configured"}
        assert client.get("/health").json()["status"] == "ok"
        invalid = client.post("/papers/search", json={"query": "graph", "limit": -1})
        assert invalid.status_code == 422
        response = client.post(
            "/documents/import", json={"source": "test", "text": "文章引用与文献耦合。"}
        )
        assert response.status_code == 202
        task_id = response.json()["task_id"]
        for _ in range(100):
            result = client.get(f"/tasks/{task_id}").json()
            if result["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert result["status"] == "completed", result
        assert client.get("/records/document").json()[0]["title"] == "导入文本"
        assert client.get(f"/tasks/{task_id}/artifacts/result.json").status_code == 200
        assert "result.json" in client.get(f"/tasks/{task_id}/files").json()
        assert client.post(f"/tasks/{task_id}/resume").status_code == 409
        events = client.get(f"/tasks/{task_id}/events")
        assert '"completed"' in events.text
        assert client.get("/tasks/not-found").status_code == 404


async def test_actual_stdio_mcp_import_search_delete(settings):
    settings.tool_transport = "stdio"
    async with Gateway(settings).open() as gateway:
        names = {t.name for t in (await gateway.session.list_tools()).tools}
        assert names == {"papers", "documents", "knowledge", "sources", "slides", "workspace", "memory", "chat"}
        result = await gateway.call(
            "documents.import", {"source": "test", "text": "真实 MCP 的文章正文，关于向量检索。"}
        )
        doc = result["document"]["id"]
        assert result["warnings"]  # no embedding model: explicit FTS fallback
        context = await gateway.call("reading.ask", {"document_id": doc, "question": "向量检索"})
        assert context["evidence"]
        await gateway.call("documents.delete", {"id": doc})
    assert gateway.session is None


async def test_actual_stdio_langgraph_execution(settings):
    from research_agent.workflows import Engine

    settings.tool_transport = "stdio"
    engine = Engine(settings)
    task = engine.create("documents.import", {"source": "stdio", "text": "持久工作流测试"})
    result = await engine.run(task["id"])
    assert result["status"] == "completed", result
    assert result["result"]["document"]["id"]


async def test_actual_stdio_with_local_embedding(settings):
    from research_agent.config import PROJECT_ROOT

    model_path = PROJECT_ROOT / "data/embedding-model"
    if not (model_path / "config.json").exists():
        pytest.skip("本地嵌入模型未初始化")
    settings.embedding_dir = model_path
    settings.tool_transport = "stdio"
    settings.tool_timeout = 60
    async with Gateway(settings).open() as gateway:
        imported = await gateway.call(
            "documents.import",
            {"source": "embedding-test", "text": "文献耦合是两篇论文共享参考文献。"},
        )
        assert not imported["warnings"]
        retrieved = await gateway.call(
            "reading.ask",
            {"document_id": imported["document"]["id"], "question": "bibliographic coupling"},
        )
        assert not retrieved["warnings"]
        assert retrieved["evidence"]


async def test_duplicate_task_claim(engine):
    task = engine.create("documents.import", {"source": "claim", "text": "测试"})
    engine.store.claim(task["id"])
    with pytest.raises(ValueError, match="运行"):
        engine.store.claim(task["id"])
