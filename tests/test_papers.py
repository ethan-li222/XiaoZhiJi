import httpx
import pytest

from research_agent.models import Paper
from research_agent.papers import deduplicate, from_openalex, normalize_doi


def oa(identifier="W1", doi="10.1/example"):
    return {
        "id": "https://openalex.org/" + identifier,
        "title": "Graph Research",
        "ids": {"doi": "https://doi.org/" + doi},
        "publication_year": 2025,
        "publication_date": "2025-10-01",
        "cited_by_count": 12,
        "abstract_inverted_index": {"Graph": [0], "research": [1]},
        "referenced_works": [],
    }


def test_normalization_and_merge():
    assert normalize_doi("https://doi.org/10.123/ABC") == "10.123/abc"
    a = from_openalex(oa())
    b = Paper(id="S2:abc", title=a.title, doi=a.doi, source_ids={"semantic": "abc"})
    papers = deduplicate([a, b])
    assert len(papers) == 1
    assert papers[0].abstract == "Graph research"
    assert papers[0].source_ids == {"openalex": a.id, "semantic": "abc"}


async def test_search_partial_sources_and_date_sort(tools):
    def handler(req):
        if "openalex" in req.url.host:
            return httpx.Response(200, json={"results": [oa(), oa()], "meta": {"count": 2}})
        return httpx.Response(403)

    tools.net.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await tools.papers.search("graph", limit=3, sort="date", year_from=2024)
    assert len(result["papers"]) == 1
    assert result["warnings"]
    assert tools.store.get(result["papers"][0]["id"], "paper")


async def test_reference_direction_pagination_and_missing_abstract(tools):
    seed = Paper(id="S2:seed", title="Seed", source_ids={"semantic": "seed"})
    tools.store.put("paper", seed.model_dump())

    def handler(req):
        if req.url.path.endswith("references"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"citedPaper": {"paperId": "ref", "title": "Reference"}},
                        {"citedPaper": None},
                    ],
                    "next": 1,
                },
            )
        return httpx.Response(
            200, json={"data": [{"citingPaper": {"paperId": "citing", "title": "Citation"}}]}
        )

    tools.net.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await tools.papers.related(seed.id, similar_limit=0, limit=1)
    assert {tuple(e[k] for k in ("source", "target", "kind")) for e in result["relations"]} == {
        ("S2:seed", "S2:ref", "cites"),
        ("S2:citing", "S2:seed", "cites"),
    }
    assert result["pagination"]["references"]["next_offset"] == 1
    assert result["papers"][1]["abstract"] == ""


async def test_title_ambiguity_returns_candidates(tools, monkeypatch):
    async def search(*args, **kwargs):
        return {
            "papers": [
                Paper(id="1", title="Graph A").model_dump(),
                Paper(id="2", title="Graph B").model_dump(),
            ]
        }

    monkeypatch.setattr(tools.papers, "search", search)
    result = await tools.papers.related("graph", similar_limit=0)
    assert result["status"] == "needs_selection"
    assert len(result["candidates"]) == 2


async def test_similarity_is_separate_relation(tools, monkeypatch):
    seed = Paper(id="S2:seed", title="引用", source_ids={"semantic": "seed"})
    tools.store.put("paper", seed.model_dump())

    async def search(*args, **kwargs):
        return {"papers": [Paper(id="other", title="引用参考文献").model_dump()], "warnings": []}

    async def s2(*args, **kwargs):
        return {"data": []}

    monkeypatch.setattr(tools.papers, "search", search)
    monkeypatch.setattr(tools.papers, "s2", s2)
    result = await tools.papers.related(seed.id)
    assert result["relations"][0]["kind"] == "similar"
    assert result["relations"][0]["score"] > 0


@pytest.mark.parametrize(
    "kwargs", [{"limit": 0}, {"query": " "}, {"sort": "bad"}, {"year_from": 2026, "year_to": 2020}]
)
async def test_invalid_search(tools, kwargs):
    with pytest.raises(ValueError):
        await tools.papers.search(**({"query": "graph"} | kwargs))
