"""One synthetic chat turn against the configured model, isolated from user materials."""

import asyncio
from datetime import datetime

from research_agent.chat import new_session
from research_agent.config import get_settings
from research_agent.workflows import Engine


async def main():
    settings = get_settings()
    settings.data_dir = (
        settings.data_dir / "chat-model-smoke" / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    settings.tool_transport = "local"
    settings.model_timeout = 90
    settings.model_max_tokens = 4096
    settings.prepare()
    engine = Engine(settings)
    engine.model.load().max_retries = 0
    session = engine.store.put("chat_session", new_session())
    task = engine.create(
        "chat.send",
        {
            "session_id": session["id"],
            "revision": 1,
            "message": "你好，请用一句中文说明你可以怎样帮助我梳理学习计划。",
            "scope": "none",
        },
    )
    result = await engine.run(task["id"])
    if result["status"] != "completed":
        raise RuntimeError("Synthetic chat failed: " + (result["error"] or "unknown"))
    assert result["result"]["answer"] and not result["result"]["sources"]
    assert len(engine.store.get(session["id"], "chat_session")["turns"]) == 1
    print(
        "Configured model chat response, schema and persistent turn passed; no user materials were used"
    )


if __name__ == "__main__":
    asyncio.run(main())
