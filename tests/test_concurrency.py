import asyncio

from conftest import run


async def test_concurrent_reading_history_is_not_lost(engine):
    doc = (
        await run(
            engine,
            "documents.import",
            {"source": "parallel", "text": "文献耦合来自共同参考文献。共引来自后续论文。"},
        )
    )["document"]["id"]
    session = (await run(engine, "reading.ask", {"document_id": doc, "question": "耦合"}))[
        "session_id"
    ]
    tasks = [
        engine.create("reading.ask", {"document_id": doc, "question": q, "session_id": session})
        for q in ("引用", "共引")
    ]
    results = await asyncio.gather(*(engine.run(t["id"]) for t in tasks))
    assert all(r["status"] == "completed" for r in results)
    history = engine.store.get(session)["history"]
    assert len(history) == 3
    assert len({h["task_id"] for h in history}) == 3


async def test_history_persistence_is_idempotent(engine):
    doc = (await run(engine, "documents.import", {"source": "persist", "text": "文献耦合"}))[
        "document"
    ]["id"]
    session = (await run(engine, "reading.ask", {"document_id": doc, "question": "耦合"}))[
        "session_id"
    ]
    entry = engine.store.get(session)["history"][0]
    engine.store.append_history(session, entry)
    assert len(engine.store.get(session)["history"]) == 1
