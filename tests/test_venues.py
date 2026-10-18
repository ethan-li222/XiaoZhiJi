import httpx

from research_agent.models import Paper
from research_agent.venues import canonical_venue, matches_venue, venue_metadata


def test_venue_claims_are_not_indexed_acceptance():
    assert canonical_venue("TAPMI") == "TPAMI"
    assert canonical_venue("Advances in Neural Information Processing Systems") == "NeurIPS"
    claimed = Paper(id="a", title="a", **venue_metadata("arXiv", "Accepted at ICLR 2025"))
    assert claimed.venue_status == "author_claim"
    assert not matches_venue(claimed, ["ICLR"])
    assert matches_venue(claimed, ["ICLR"], include_claimed=True)
    unknown = Paper(id="b", title="ICML paper title")
    assert not matches_venue(unknown, ["ICML"])
    indexed = Paper(id="c", title="c", **venue_metadata("CVPR", publisher="IEEE"))
    assert matches_venue(indexed, ["CVPR"], "IEEE")


async def test_search_filters_candidates_and_keeps_scope_warning(tools):
    def handler(request):
        if "openalex" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "title": "ML result",
                            "primary_location": {
                                "source": {
                                    "display_name": "International Conference on Machine Learning"
                                }
                            },
                        },
                        {
                            "id": "https://openalex.org/W2",
                            "title": "ICML in title is not acceptance",
                        },
                    ]
                },
            )
        return httpx.Response(403)

    tools.net.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await tools.papers.search("ML", limit=5, venues=["ICML"])
    assert [paper["id"] for paper in result["papers"]] == ["https://openalex.org/W1"]
    assert any("本次候选" in warning for warning in result["warnings"])
    assert result["venue_links"][0]["venue"] == "ICML"
