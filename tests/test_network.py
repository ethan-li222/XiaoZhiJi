import time

import httpx
import pytest


async def test_retry_cache_and_stale_fallback(tools, monkeypatch):
    attempts = []

    async def no_sleep(_):
        pass

    monkeypatch.setattr("research_agent.network.asyncio.sleep", no_sleep)

    def handler(req):
        attempts.append(req)
        return httpx.Response(429 if len(attempts) < 3 else 200, json={"ok": True})

    tools.net.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    url = "https://example.org/data"
    assert await tools.net.get(url) == {"ok": True}
    assert len(attempts) == 3
    assert await tools.net.get(url) == {"ok": True}
    assert len(attempts) == 3
    with tools.store.connect() as db:
        db.execute("UPDATE cache SET expires=?", (time.time() - 1,))
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    assert await tools.net.get(url) == {"ok": True}
    assert tools.net.warnings


async def test_budget_and_secret_not_in_error(tools):
    tools.settings.source_requests_per_run = 0
    with pytest.raises(ValueError, match="预算"):
        await tools.net.get("https://api.openalex.org/works", {"api_key": "test-secret"})
    tools.settings.source_requests_per_run = 5
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(403))
    )
    with pytest.raises(ValueError) as exc:
        await tools.net.get("https://api.openalex.org/works", {"api_key": "test-secret"})
    assert "test-secret" not in str(exc.value)
    assert "HTTP 403" in str(exc.value)
