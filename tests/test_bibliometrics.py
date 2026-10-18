import asyncio
import math
import time

import pytest
from conftest import run

from research_agent.bibliometrics import LiteratureMap, compare_neighborhoods
from research_agent.models import Paper


async def test_slow_source_becomes_explicit_partial_neighborhood(tools, monkeypatch):
    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(tools.papers, "s2", slow)
    collector = LiteratureMap(tools.papers, 5, 8)
    collector.deadline = time.monotonic() + 0.01
    result = await collector.neighbors("S2:slow", "references")
    assert not result["complete"] and not result["ids"]
    assert "超时" in result["error"]


def test_overlap_is_symmetric_normalized_and_evidence_backed():
    a = {"references": {"r1", "r2"}, "citations": {"c1"}}
    b = {"references": {"r1"}, "citations": {"c1", "c2"}}
    scores = compare_neighborhoods(a, b)
    assert scores == compare_neighborhoods(b, a)
    assert scores["score"] == pytest.approx(1 / math.sqrt(2))
    assert scores["shared_reference_ids"] == ["r1"]
    assert scores["shared_citing_ids"] == ["c1"]
    assert compare_neighborhoods(a, {"references": set(), "citations": set()})["score"] == 0


def install_openalex(tools, monkeypatch, truncated=False):
    # A and B never cite each other. They share R and are jointly cited by C.
    refs = {"W1": ["W3"], "W2": ["W3"], "W3": [], "W4": ["W1", "W2"], "W5": []}

    def work(short):
        return {
            "id": "https://openalex.org/" + short,
            "title": short,
            "referenced_works": ["https://openalex.org/" + r for r in refs[short]],
            "publication_year": 2020,
            "cited_by_count": 5,
        }

    async def oa(suffix="", params=None):
        if suffix:
            return work(suffix.rsplit("/", 1)[-1])
        condition = params["filter"]
        if condition.startswith("openalex:"):
            return {"results": [work(i) for i in condition.split(":", 1)[1].split("|")]}
        target = condition.split(":", 1)[1]
        rows = [work(i) for i, outgoing in refs.items() if target in outgoing]
        return {"results": rows, "meta": {"count": len(rows) + (100 if truncated else 0)}}

    monkeypatch.setattr(tools.papers, "oa", oa)
    tools.store.put(
        "paper",
        Paper(
            id="https://openalex.org/W1",
            title="W1",
            source_ids={"openalex": "https://openalex.org/W1"},
        ).model_dump(),
    )
    return "https://openalex.org/W1"


async def test_map_discovers_non_citing_peer_prior_and_derivative(engine, tools, monkeypatch):
    seed = install_openalex(tools, monkeypatch)
    result = await run(
        engine, "papers.map", {"seed": seed, "candidate_limit": 8, "limit": 5, "sample_size": 5}
    )
    edge = next(
        e
        for e in result["relations"]
        if {e["source"], e["target"]} == {seed, "https://openalex.org/W2"}
    )
    assert edge["coupling_score"] == 1 and edge["co_citation_score"] == 1
    assert not result["citation_relations"]
    assert result["prior_works"][0]["id"] == "https://openalex.org/W3"
    assert result["derivative_works"][0]["id"] == "https://openalex.org/W4"
    assert result["prior_works"][0]["support_count"] == 2
    assert result["coverage"]["requests"] <= 50
    assert not tools.store.list("knowledge")


async def test_truncation_and_no_fabricated_links(tools, monkeypatch):
    seed = install_openalex(tools, monkeypatch, truncated=True)
    result = await LiteratureMap(tools.papers, 5, 8).build(seed, 5)
    assert any(not n["citations"]["complete"] for n in result["coverage"]["neighborhoods"])
    assert all(
        e["shared_reference_count"] + e["shared_citing_count"] > 0 for e in result["relations"]
    )


async def test_semantic_fallback_and_budget(tools, monkeypatch):
    async def oa(*args, **kwargs):
        raise ValueError("OA unavailable")

    refs = {"a": ["r"], "b": ["r"], "r": [], "c": ["a", "b"]}

    def paper(i):
        return {"paperId": i, "title": i}

    async def s2(suffix, params):
        if "/" not in suffix:
            return paper(suffix)
        i, direction = suffix.split("/")
        identifiers = (
            refs[i] if direction == "references" else [k for k, v in refs.items() if i in v]
        )
        field = "citedPaper" if direction == "references" else "citingPaper"
        return {"data": [{field: paper(k)} for k in identifiers]}

    monkeypatch.setattr(tools.papers, "oa", oa)
    monkeypatch.setattr(tools.papers, "s2", s2)
    tools.store.put("paper", Paper(id="S2:a", title="a", source_ids={"semantic": "a"}).model_dump())
    result = await LiteratureMap(tools.papers, 5, 8).build("S2:a", 5)
    assert result["coverage"]["provider"] == "semantic"
    assert any(e["score"] == 1 for e in result["relations"])
    collector = LiteratureMap(tools.papers, 5, 8)
    collector.budget = 4
    partial = await collector.build("S2:a", 5)
    assert partial["coverage"]["requests"] == 4
    assert any("预算" in w for w in partial["warnings"])


async def test_isolated_origin_and_invalid_limits(engine, tools, monkeypatch):
    seed = install_openalex(tools, monkeypatch)

    async def isolated(*args, **kwargs):
        return {
            "id": seed,
            "title": "Isolated",
            "referenced_works": [],
            "results": [],
            "meta": {"count": 0},
        }

    monkeypatch.setattr(tools.papers, "oa", isolated)
    result = await LiteratureMap(tools.papers, 5, 8).build(seed, 5)
    assert len(result["papers"]) == 1 and not result["relations"]
    assert any("没有足够" in w for w in result["warnings"])
    with pytest.raises(ValueError):
        engine.create("papers.map", {"seed": seed, "limit": 40, "candidate_limit": 3})
