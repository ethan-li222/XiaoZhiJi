import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import SecretStr

from research_agent.llm import Model
from research_agent.models import GroundedAnswer


@pytest.mark.parametrize("provider", ["api", "ollama"])
async def test_real_model_adapter_against_local_protocol_server(settings, provider):
    received = []
    answer = json.dumps({"answer": "协议验证通过", "evidence_ids": []}, ensure_ascii=False)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, body))
            if self.path.endswith("chat/completions"):
                data = {
                    "id": "test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": answer},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            else:
                data = {
                    "model": "test-model",
                    "created_at": "2026-10-05T00:00:00Z",
                    "message": {"role": "assistant", "content": answer},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 1,
                    "eval_count": 1,
                }
            content = (json.dumps(data, ensure_ascii=False) + "\n").encode()
            self.send_response(200)
            self.send_header(
                "Content-Type", "application/json" if provider == "api" else "application/x-ndjson"
            )
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings.model_provider = provider
        settings.model_name = "test-model"
        settings.model_api_key = SecretStr("local-test-key")
        settings.model_base_url = f"http://127.0.0.1:{server.server_port}" + (
            "/v1" if provider == "api" else ""
        )
        result = await Model(settings).generate("返回测试 JSON", {}, GroundedAnswer)
        assert result.answer == "协议验证通过"
        assert received[0][0] == ("/v1/chat/completions" if provider == "api" else "/api/chat")
        assert received[0][1]["model"] == "test-model"
        messages = received[0][1]["messages"]
        assert [m["role"] for m in messages] == ["system", "user"]
        assert "JSON Schema" in messages[0]["content"]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_missing_model_configuration_is_actionable(settings):
    with pytest.raises(ValueError, match="RESEARCH_MODEL_API_KEY"):
        Model(settings).load()


async def test_structured_output_repair_is_bounded(settings):
    from types import SimpleNamespace

    class InvalidThenValid:
        def __init__(self, valid):
            self.calls = []
            self.valid = valid

        async def ainvoke(self, messages):
            self.calls.append(list(messages))
            content = '{"properties":{"answer":"wrong"}}'
            if self.valid and len(self.calls) == 2:
                content = '{"answer":"修正后答案","evidence_ids":["source"]}'
            return SimpleNamespace(content=content)

    model = Model(settings)
    model._model = InvalidThenValid(True)
    result = await model.generate("回答", {}, GroundedAnswer)
    assert result.evidence_ids == ["source"]
    assert len(model._model.calls) == 2
    model._model = InvalidThenValid(False)
    with pytest.raises(ValueError, match="结构"):
        await model.generate("回答", {}, GroundedAnswer)
    assert len(model._model.calls) == 2


async def test_known_single_slide_envelope_is_validated(settings):
    from types import SimpleNamespace

    from research_agent.models import Slide

    class WrappedSlide:
        async def ainvoke(self, messages):
            return SimpleNamespace(content='{"slide":{"title":"技术变化","bullets":["中文要点"]}}')

    model = Model(settings)
    model._model = WrappedSlide()
    result = await model.generate("修改单页", {}, Slide)
    assert result.title == "技术变化"
    assert result.bullets == ["中文要点"]
