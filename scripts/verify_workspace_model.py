"""Synthetic note smoke test against the configured model; isolated from user materials."""

import asyncio
from datetime import datetime

from research_agent.config import get_settings
from research_agent.workflows import Engine


async def main():
    settings = get_settings()
    settings.data_dir = (
        settings.data_dir / "model-workspace-smoke" / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    settings.tool_transport = "local"
    settings.model_timeout = 90
    settings.model_max_tokens = 4096
    settings.prepare()
    engine = Engine(settings)
    engine.model.load().max_retries = 0

    async def run(action, params):
        task = engine.create(action, params)
        result = await engine.run(task["id"])
        if result["status"] != "completed":
            raise RuntimeError("Synthetic workspace smoke task failed: " + action)
        return result["result"]

    project = (
        await run(
            "workspace.project.save", {"name": "合成验证项目", "question": "如何隔离检索策略的影响"}
        )
    )["entry"]
    material = await run(
        "workspace.import",
        {
            "project_id": project["id"],
            "source": "synthetic-smoke",
            "text": "合成测试材料：比较检索策略时，应固定生成器、数据划分和评估指标。",
        },
    )
    note = await run(
        "workspace.annotation.save",
        {
            "project_id": project["id"],
            "document_id": material["document"]["id"],
            "text": "个人合成笔记：先固定生成器，用同一验证集比较两种检索策略，结论仍待实验。",
            "kind": "method",
        },
    )
    result = await run("workspace.synthesize", {"project_id": project["id"], "days": 7})
    assert result["synthesis"]["overview"]
    allowed = {note["entry"]["id"]}
    for row in [
        *result["synthesis"]["findings"],
        *result["synthesis"]["disagreements"],
        *result["synthesis"]["candidate_ideas"],
    ]:
        assert set(row["source_ids"]) <= allowed
    print("Configured model synthetic research synthesis: passed; user materials were not used")


if __name__ == "__main__":
    asyncio.run(main())
