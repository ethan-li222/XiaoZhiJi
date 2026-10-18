"""Non-LLM live verification; does not send user documents or invoke paid models."""

import asyncio
import json

from research_agent.config import get_settings
from research_agent.models import new_id
from research_agent.tools import Tools
from research_agent.workflows import Engine


async def main():
    settings = get_settings()
    settings.data_dir = settings.data_dir / "verification" / new_id()
    settings.prepare()
    tools = Tools(settings)
    engine = Engine(settings, local_tools=tools)
    search_task = engine.create(
        "papers.search", {"query": "retrieval augmented generation", "limit": 3}
    )
    search = await engine.run(search_task["id"])
    result = search.get("result") or {}
    papers = result.get("papers", [])
    summary = {
        "search_status": search["status"],
        "paper_count": len(papers),
        "source_providers": sorted({s for p in papers for s in p["source_ids"]}),
        "search_warnings": result.get("warnings", []),
        "output": str(settings.data_dir),
    }
    if papers:
        related_task = engine.create(
            "papers.related", {"seed": papers[0]["id"], "limit": 2, "similar_limit": 2}
        )
        related = await engine.run(related_task["id"])
        graph = related.get("result") or {}
        summary.update(
            related_status=related["status"],
            relation_count=len(graph.get("relations", [])),
            relation_types=sorted({e["kind"] for e in graph.get("relations", [])}),
            related_warnings=graph.get("warnings", []),
            related_error=related.get("error"),
        )
    industry = await tools.reports.collect(
        "LangGraph",
        kind="industry",
        days=30,
        sources=[{"type": "github", "repo": "langchain-ai/langgraph"}],
    )
    summary.update(
        industry_source_count=len(industry["sources"]), industry_warnings=industry["warnings"]
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
