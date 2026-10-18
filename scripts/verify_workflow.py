"""Explicit live verification using the configured model and public sample material."""

import argparse
import asyncio
import json
import sys

from research_agent.config import PROJECT_ROOT, get_settings
from research_agent.models import new_id
from research_agent.preview import render_preview
from research_agent.requests import validate_params
from research_agent.workflows import Engine


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", help="继续已有验证目录，复用已完成任务并恢复失败任务")
    args = parser.parse_args()
    settings.data_dir = (
        type(settings.data_dir)(args.data_dir).resolve()
        if args.data_dir
        else settings.data_dir / "verification" / new_id()
    )
    settings.prepare()
    engine = Engine(settings)
    summary = {"output": str(settings.data_dir), "model": settings.model_name, "tasks": []}
    summary_path = settings.data_dir / "summary.json"

    def save():
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    async def run(action, params):
        existing = next(
            (
                t
                for t in engine.store.task_list()
                if args.data_dir
                and t["action"] == action
                and t["params"] == validate_params(action, params)
            ),
            None,
        )
        task = existing or engine.create(action, params)
        print(f"START {action} {task['id']}", flush=True)
        result = (
            task
            if task["status"] == "completed"
            else await engine.run(task["id"], resume=existing is not None)
        )
        for attempt in range(2):
            if result["status"] == "completed" or result.get("error") != "OpenAIRateLimitError":
                break
            print(f"RETRY {action}: provider busy; checkpoint {task['id']}", flush=True)
            await asyncio.sleep(10 * (attempt + 1))
            result = await engine.run(task["id"], resume=True)
        summary["tasks"].append({k: result.get(k) for k in ("id", "action", "status", "error")})
        save()
        if result["status"] != "completed":
            raise RuntimeError(f"{action}: {result['error']} (task {task['id']})")
        print(f"PASS {action}", flush=True)
        return result["result"]

    imported = await run("documents.import", {"source": str(PROJECT_ROOT / "examples/article.md")})
    document = imported["document"]["id"]
    first = await run(
        "reading.ask", {"document_id": document, "question": "文献耦合是什么？请根据原文说明。"}
    )
    second = await run(
        "reading.ask",
        {
            "document_id": document,
            "session_id": first["session_id"],
            "question": "它与共引有什么区别？",
        },
    )
    assert first["evidence"] and second["evidence"]
    assert len(engine.store.get(first["session_id"])["history"]) == 2
    saved = await run("knowledge.save", {"session_id": first["session_id"], "tags": ["引用分析"]})
    found = await run("knowledge.search", {"query": "bibliographic coupling and co-citation"})
    assert any(e["id"] == saved["entry"]["id"] for e in found["entries"])
    research = await run(
        "reports.generate",
        {"topic": "retrieval augmented generation", "kind": "research", "days": 30, "limit": 3},
    )
    if not research["report"]["sources"]:
        summary["research_recent_empty"] = True
        research = await run(
            "reports.generate",
            {
                "topic": "retrieval augmented generation",
                "kind": "research",
                "days": 366,
                "limit": 3,
            },
        )
    assert research["report"]["sources"] and research["report"]["sections"]
    industry = await run(
        "reports.generate",
        {
            "topic": "LangGraph",
            "kind": "industry",
            "days": 30,
            "limit": 3,
            "sources": [{"type": "github", "repo": "langchain-ai/langgraph"}],
        },
    )
    assert industry["report"]["sources"] and industry["report"]["sections"]
    summary["reports"] = {"research": research["artifacts"], "industry": industry["artifacts"]}
    outline = await run("slides.outline", {"source": industry["report"]["id"], "pages": 4})
    revised = await run(
        "slides.revise",
        {"deck": outline["deck"], "page": 2, "instruction": "使用更简短的中文要点，保留来源引用。"},
    )
    assert all(
        a == b
        for i, (a, b) in enumerate(
            zip(outline["deck"]["slides"], revised["deck"]["slides"], strict=True)
        )
        if i != 1
    )
    built = await run("slides.build", {"deck": revised["deck"]})
    summary["presentation"] = built
    save()
    print(json.dumps(built, ensure_ascii=False), flush=True)
    pptx = built.get("pptx") or built.get("path")
    if not pptx:
        raise RuntimeError("Missing PPTX artifact")
    summary["preview"] = await asyncio.to_thread(render_preview, pptx)
    save()
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
