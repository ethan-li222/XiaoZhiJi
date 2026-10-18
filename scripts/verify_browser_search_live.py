"""Search public paper pages in local Chrome with isolated verification data."""

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
                / "data/browser-search-live"
                / datetime.now(UTC).strftime("%Y%m%d-%H%M%S"),
                "tool_transport": "local",
            }
        )
        .prepare()
    )
    engine = Engine(settings)
    task = engine.create("papers.search", {"query": "attention", "mode": "browser", "limit": 4})
    task = await engine.run(task["id"])
    result = task.get("result") or {}
    summary = {
        "status": task["status"],
        "error": task.get("error"),
        "papers": len(result.get("papers", [])),
        "pdf_links": sum(bool(p.get("pdf_url")) for p in result.get("papers", [])),
        "sources": result.get("search_pages"),
        "warnings": result.get("warnings"),
        "data_dir": str(settings.data_dir),
    }
    (settings.data_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    if task["status"] != "completed" or not result.get("papers") or not all(
        source["status"] == "completed" for source in result.get("search_pages", [])
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
