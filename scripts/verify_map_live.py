"""Opt-in live bibliometric verification; isolated data, no cloud-model requests."""

import asyncio
import json
from datetime import UTC, datetime

from research_agent.config import PROJECT_ROOT, get_settings
from research_agent.workflows import Engine


async def main():
    settings = (
        get_settings()
        .model_copy(
            update={
                "data_dir": PROJECT_ROOT
                / "data"
                / "map-live"
                / datetime.now(UTC).strftime("%Y%m%d-%H%M%S"),
                "tool_transport": "local",
                "http_timeout": 10,
                "source_requests_per_run": 40,
            }
        )
        .prepare()
    )
    engine = Engine(settings)
    task = engine.create(
        "papers.map",
        {"seed": "10.1038/nature14539", "limit": 8, "candidate_limit": 12, "sample_size": 15},
    )
    result = await engine.run(task["id"])
    graph = result.get("result") or {}
    summary = {
        "status": result["status"],
        "error": result.get("error"),
        "papers": len(graph.get("papers", [])),
        "relations": len(graph.get("relations", [])),
        "coverage": graph.get("coverage"),
        "warnings": graph.get("warnings"),
        "data_dir": str(settings.data_dir),
    }
    (settings.data_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "coverage"}, ensure_ascii=False))
    if result["status"] != "completed" or not graph.get("relations"):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
