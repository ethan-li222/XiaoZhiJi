import pytest
from conftest import run
from pypdf import PdfWriter

from research_agent.embedding import Embedder


async def test_context_history_save_search_and_delete(engine, model, tools):
    result = await run(
        engine,
        "documents.import",
        {
            "source": "test",
            "text": "# 文献耦合\n\n两篇论文引用相同的参考文献。\n\n共引是第三篇论文同时引用它们。",
        },
    )
    doc = result["document"]["id"]
    first = await run(
        engine,
        "reading.ask",
        {
            "document_id": doc,
            "question": "文献耦合是什么",
            "selection": "两篇论文引用相同的参考文献。",
        },
    )
    assert first["evidence"][0]["document_id"] == doc
    assert first["evidence"][0]["section"] == "文献耦合"
    assert tools.store.list("knowledge") == []
    await run(
        engine,
        "reading.ask",
        {"document_id": doc, "session_id": first["session_id"], "question": "与共引区别"},
    )
    assert len(model.calls[-1]["history"]) == 1
    saved = await run(
        engine, "knowledge.save", {"session_id": first["session_id"], "tags": ["引用"]}
    )
    found = await run(engine, "knowledge.search", {"query": "共享参考文献"})
    assert found["entries"][0]["id"] == saved["entry"]["id"]
    await run(engine, "knowledge.delete", {"id": saved["entry"]["id"]})
    assert tools.store.search("参考文献", "knowledge") == []
    await run(engine, "documents.delete", {"id": doc})
    assert not tools.store.list("session")
    assert not tools.store.list("chunk")


async def test_session_document_isolation(engine):
    a = (await run(engine, "documents.import", {"source": "a", "text": "文献耦合"}))["document"][
        "id"
    ]
    b = (await run(engine, "documents.import", {"source": "b", "text": "共引"}))["document"]["id"]
    session = (await run(engine, "reading.ask", {"document_id": a, "question": "耦合"}))[
        "session_id"
    ]
    task = engine.create(
        "reading.ask", {"document_id": b, "question": "共引", "session_id": session}
    )
    result = await engine.run(task["id"])
    assert result["status"] == "failed"
    assert "另一篇文章" in result["error"]


async def test_missing_embedding_falls_back_to_fts(tools):
    tools.documents.embedder = Embedder(tools.settings)
    result = await tools.documents.import_document("text", text="深度学习模型使用向量检索。")
    doc = result["document"]["id"]
    assert result["warnings"]
    found = await tools.documents.retrieve(doc, "向量检索")
    assert found["evidence"]
    assert found["warnings"]


async def test_invalid_evidence_and_resume_does_not_repeat_collect(engine, model):
    doc = (
        await run(
            engine, "documents.import", {"source": "test", "text": "共享参考文献产生文献耦合。"}
        )
    )["document"]["id"]
    task = engine.create("reading.ask", {"document_id": doc, "question": "文献耦合"})
    model.invalid = True
    failed = await engine.run(task["id"])
    assert failed["status"] == "failed"
    assert failed["stage"] == "compose"
    assert len(engine.store.list("session")) == 1
    model.invalid = False
    completed = await engine.run(task["id"], resume=True)
    assert completed["status"] == "completed"
    assert len(engine.store.list("session")) == 1
    assert len(engine.store.list("session")[0]["history"]) == 1


async def test_scanned_pdf_is_explicit_error(tools, tmp_path):
    path = tmp_path / "scanned.pdf"
    pdf = PdfWriter()
    pdf.add_blank_page(width=500, height=500)
    pdf.write(path)
    with pytest.raises(ValueError, match="扫描"):
        await tools.documents.import_document(str(path))


async def test_import_is_idempotent(tools):
    first = await tools.documents.import_document("text", text="测试文章内容")
    second = await tools.documents.import_document("text", text="测试文章内容")
    assert first["document"]["id"] == second["document"]["id"]
    assert len(tools.store.list("chunk")) == 1
