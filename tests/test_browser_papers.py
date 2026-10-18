import httpx
import pytest

from research_agent.models import Paper


def result():
    return {
        "papers": [
            Paper(
                id="arxiv:2401.12345",
                title="Arxiv result",
                year=2024,
                arxiv_id="2401.12345",
                pdf_url="https://arxiv.org/pdf/2401.12345",
                source_ids={"arxiv": "2401.12345", "browser": "arxiv"},
            ).model_dump(),
            Paper(
                id="google-research:peer",
                title="Google result",
                year=2025,
                source_ids={
                    "google_research": "https://research.google/pubs/peer/",
                    "browser": "google_research",
                },
            ).model_dump(),
        ],
        "search_pages": [
            {
                "site": "arxiv",
                "status": "completed",
                "count": 1,
                "url": "https://arxiv.org/search/",
            },
            {
                "site": "google_research",
                "status": "completed",
                "count": 1,
                "url": "https://research.google/pubs/",
            },
        ],
        "transport": "browser",
        "warnings": [],
    }


async def test_explicit_browser_mode_bypasses_api_and_saves_only_papers(tools, monkeypatch):
    calls = []

    async def browser(*args):
        calls.append(args)
        return result()

    async def forbidden(*args, **kwargs):
        raise AssertionError("API must not run")

    monkeypatch.setattr(tools.papers.browser, "search", browser)
    monkeypatch.setattr(tools.papers, "oa", forbidden)
    found = await tools.call(
        "papers.search",
        {"query": "attention", "mode": "google_research_browser", "year_from": 2025},
    )
    assert calls[0][2] == "google_research"
    assert len(found["papers"]) == 1 and found["papers"][0]["year"] == 2025
    assert tools.store.list("paper")
    assert not tools.store.list("knowledge")


async def test_auto_429_fallback_and_both_source_results(tools, monkeypatch):
    tools.settings.browser_enabled = True

    async def limited(*args, **kwargs):
        raise ValueError("OpenAlex HTTP 429")

    async def browser(*args):
        return result()

    monkeypatch.setattr(tools.papers, "oa", limited)
    monkeypatch.setattr(tools.papers.browser, "search", browser)
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"/>')
        )
    )
    found = await tools.call("papers.search", {"query": "attention", "mode": "auto", "limit": 2})
    assert found["transport"] == "browser"
    assert {p["source_ids"]["browser"] for p in found["papers"]} == {"arxiv", "google_research"}
    assert any("本地 Chrome" in w for w in found["warnings"])


async def test_api_only_mode_never_uses_browser(tools, monkeypatch):
    tools.settings.browser_enabled = True

    async def limited(*args, **kwargs):
        raise ValueError("OpenAlex HTTP 429")

    async def forbidden(*args):
        raise AssertionError("browser must not run")

    monkeypatch.setattr(tools.papers, "oa", limited)
    monkeypatch.setattr(tools.papers.browser, "search", forbidden)
    tools.net.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"/>')
        )
    )
    found = await tools.call("papers.search", {"query": "attention", "mode": "api"})
    assert not found["papers"]
    assert any("429" in w for w in found["warnings"])


async def test_browser_failure_is_visible_and_limits_are_validated(tools, monkeypatch):
    async def unavailable(*args):
        raise ValueError("本地 Chrome 不可用")

    monkeypatch.setattr(tools.papers.browser, "search", unavailable)
    with pytest.raises(ValueError, match="Chrome"):
        await tools.call("papers.search", {"query": "attention", "mode": "browser"})
    with pytest.raises(ValueError):
        await tools.call("papers.search", {"query": "attention", "mode": "invalid"})
