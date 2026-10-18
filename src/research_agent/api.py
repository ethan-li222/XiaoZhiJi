import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .access import AccessGate
from .config import PROJECT_ROOT, get_settings
from .models import TaskRequest
from .personal_memory import ReadingPosition
from .workflows import Engine


def create_app(engine=None):
    import mimetypes

    # Windows registry may classify .mjs as text/plain; module workers require JS MIME.
    mimetypes.add_type("text/javascript", ".mjs")
    running = {}

    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = engine or Engine(get_settings())
        app.state.engine.interrupted_tasks()
        yield
        pending = list(running.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    app = FastAPI(title="小知己", version="0.2.0", lifespan=lifespan)
    AccessGate(engine.settings if engine else get_settings()).install(app)
    static = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static), name="static")
    pdfjs = PROJECT_ROOT / "ppt/node_modules/pdfjs-dist"
    if pdfjs.is_dir():
        app.mount("/pdfjs", StaticFiles(directory=pdfjs), name="pdfjs")

    @app.get("/reader/library")
    def reader_library():
        import hashlib

        documents = service().store.list("document")
        linked = {d.get("paper_id") for d in documents}
        downloaded = []
        for paper in service().store.list("paper"):
            path = (
                service().settings.data_dir
                / "paper-downloads"
                / (hashlib.sha256(paper["id"].encode()).hexdigest()[:24] + ".pdf")
            )
            if path.is_file() and paper["id"] not in linked:
                downloaded.append(
                    {"id": paper["id"], "title": paper["title"], "paper_id": paper["id"]}
                )
        return {"documents": documents, "downloaded": downloaded}

    def document_pdf_path(document):
        path = Path(document.get("pdf_path") or document.get("source") or "").resolve()
        roots = [
            service().settings.data_dir / d
            for d in ("documents", "library", "uploads", "paper-downloads")
        ]
        if (
            path.suffix.lower() != ".pdf"
            or not path.is_file()
            or not any(path.is_relative_to(r.resolve()) for r in roots)
        ):
            raise ValueError("该文档没有已归档的 PDF，可阅读提取正文")
        return path

    @app.get("/reader/documents/{document_id}")
    def reader_document(document_id: str):
        try:
            document = service().store.get(document_id, "document")
            try:
                document_pdf_path(document)
                pdf = f"/reader/documents/{document_id}/pdf"
            except ValueError:
                pdf = None
            return {
                "document": document,
                "pdf_url": pdf,
                "chunks": service().store.list("chunk", document_id),
                "notes": [
                    n
                    for n in service().store.list("personal_note")
                    if n.get("document_id") == document_id and n["status"] != "archived"
                ],
                "progress": next(iter(service().store.list("reading_position", document_id)), None),
            }
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.get("/reader/documents/{document_id}/pdf")
    def reader_pdf(document_id: str):
        try:
            path = document_pdf_path(service().store.get(document_id, "document"))
            return FileResponse(path, media_type="application/pdf")
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post("/reader/documents/{document_id}/position")
    def reading_position(document_id: str, body: ReadingPosition):
        from .models import now

        try:
            document = service().store.get(document_id, "document")
            pages = document.get("page_count") or max(
                (c.get("page") or 1 for c in service().store.list("chunk", document_id)), default=1
            )
            if body.page > pages:
                raise ValueError("页码超出文档范围")
            item = {
                "id": "position-" + document_id,
                "document_id": document_id,
                "page": body.page,
                "updated_at": now(),
            }
            service().store.put("reading_position", item, parent=document_id)
            return item
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/memory/state")
    def memory_state():
        notes = service().store.list("personal_note")
        for note in notes:
            note["missing_sources"] = []
            for identifier, kind in [
                (note.get("document_id"), "document"),
                *((i, "personal_note") for i in note["source_ids"]),
            ]:
                if identifier:
                    try:
                        service().store.get(identifier, kind)
                    except ValueError:
                        note["missing_sources"].append(identifier)
        return {
            "notes": notes,
            "notebooks": sorted({n["notebook"] for n in notes}),
            "reading_knowledge": service().store.list("knowledge"),
        }

    @app.post("/chat/sessions", status_code=201)
    def create_chat():
        from .chat import new_session

        return service().store.put("chat_session", new_session())

    def chat_pending(session_id):
        return [
            t
            for t in service().store.task_list()
            if t["action"] == "chat.send"
            and t["params"]["session_id"] == session_id
            and t["status"] in {"pending", "running"}
        ]

    @app.get("/chat/sessions")
    def chat_sessions():
        return [
            {
                "id": s["id"],
                "title": s["title"],
                "revision": s["revision"],
                "updated_at": s["updated_at"],
                "turn_count": len(s["turns"]),
            }
            for s in sorted(
                service().store.list("chat_session"), key=lambda s: s["updated_at"], reverse=True
            )
        ]

    @app.get("/chat/sessions/{session_id}")
    def get_chat(session_id: str):
        try:
            session = service().store.get(session_id, "chat_session")
            pending = chat_pending(session_id)
            last = next(
                iter(
                    sorted(
                        (
                            t
                            for t in service().store.task_list()
                            if t["action"] == "chat.send"
                            and t["params"]["session_id"] == session_id
                        ),
                        key=lambda t: t["created_at"],
                        reverse=True,
                    )
                ),
                None,
            )
            return {
                **session,
                "pending_task_id": pending[0]["id"] if pending else None,
                "pending_message": pending[0]["params"]["message"] if pending else None,
                "failed_task": {
                    "id": last["id"],
                    "message": last["params"]["message"],
                    "error": last["error"],
                }
                if last and last["status"] in {"failed", "interrupted"}
                else None,
            }
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.delete("/chat/sessions/{session_id}")
    def delete_chat(session_id: str):
        get_chat(session_id)
        if chat_pending(session_id):
            raise HTTPException(409, "请等待该会话的回答完成后再删除")
        service().store.delete(session_id)
        return {"deleted": session_id}

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(static / "index.html")

    @app.get("/info")
    def info():
        settings = service().settings
        return {
            "application": "research-agent",
            "model": settings.model_name,
            "model_configured": settings.model_provider == "ollama"
            or bool(settings.model_api_key.get_secret_value()),
        }

    def service():
        return app.state.engine

    def workspace_service():
        if not hasattr(app.state, "workspace"):
            if service().local_tools is not None:
                app.state.workspace = service().local_tools.workspace
            else:
                from .tools import Tools

                app.state.workspace = Tools(service().settings).workspace
        return app.state.workspace

    @app.get("/workspace/state")
    async def workspace_state(
        project_id: str | None = None, days: int = Query(default=7, ge=1, le=366)
    ):
        from .workspace_insights import WorkspaceInsights

        try:
            workspace = workspace_service()
            projects = service().store.list("project")
            result = {"projects": projects}
            for kind in ("library", "annotation", "idea", "experiment", "decision"):
                result[kind] = [
                    r
                    for r in service().store.list(kind)
                    if not project_id or r["project_id"] == project_id
                ]
            doc_ids = {r.get("document_id") for r in result["library"]}
            result["knowledge"] = [
                k
                for k in service().store.list("knowledge")
                if k["document_id"] in doc_ids and k.get("status") == "confirmed"
            ]
            result["personal_notes"] = [
                n
                for n in service().store.list("personal_note")
                if n.get("document_id") in doc_ids and n["status"] == "confirmed"
            ]
            for idea in result["idea"]:
                idea["invalid_source_ids"] = []
                for identifier in idea["source_ids"]:
                    try:
                        workspace.source(identifier, idea["project_id"])
                    except ValueError:
                        idea["invalid_source_ids"].append(identifier)
            result["stats"] = await WorkspaceInsights(workspace).stats(project_id, days)
            return result
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/workspace/library/{item_id}/text")
    def material_text(item_id: str, page: int | None = Query(default=None, ge=1)):
        try:
            item = service().store.get(item_id, "library")
            document = service().store.get(item.get("document_id"), "document")
            chunks = service().store.list("chunk", document["id"])
            return {
                "item": item,
                "document": document,
                "pages": sorted({c["page"] for c in chunks if c["page"] is not None}),
                "chunks": [c for c in chunks if page is None or c["page"] == page],
            }
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post("/workspace/uploads", status_code=201)
    async def upload_document(
        request: Request, filename: str = Query(min_length=1, max_length=200)
    ):
        import re

        from .models import new_id

        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".txt", ".md"}:
            raise HTTPException(422, "仅支持 PDF、TXT 和 Markdown 文件")
        raw = await request.body()
        if not raw or (suffix == ".pdf" and not raw.lstrip().startswith(b"%PDF-")):
            raise HTTPException(422, "文件为空或内容不是有效 PDF")
        if suffix != ".pdf":
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                raise HTTPException(422, "文本文件请使用 UTF-8 编码") from None
        directory = service().settings.data_dir / "uploads"
        directory.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^\w-]", "_", Path(filename).stem)[:80]
        path = directory / (new_id() + "-" + stem + suffix)
        path.write_bytes(raw)
        return {"source": str(path), "filename": filename, "size": len(raw)}

    @app.get("/workspace/library/{item_id}/pdf")
    def material_pdf(item_id: str, download: bool = False):
        try:
            item = service().store.get(item_id, "library")
            path = Path(item.get("pdf_path") or "").resolve()
            root = (service().settings.data_dir / "library").resolve()
            if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != ".pdf":
                raise ValueError("此材料尚无已归档 PDF")
            return FileResponse(
                path, media_type="application/pdf", filename="paper.pdf" if download else None
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    def start(task, resume=False):
        future = asyncio.create_task(service().run(task["id"], resume=resume))
        running[task["id"]] = future
        future.add_done_callback(lambda _: running.pop(task["id"], None))
        return {"task_id": task["id"], "status": "pending"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/tasks", status_code=202)
    async def submit(body: TaskRequest):
        if len(running) >= service().settings.max_parallel_tasks:
            raise HTTPException(429, "正在执行的任务较多，请等待一个任务结束后再提交")
        try:
            if body.action == "chat.send" and chat_pending(body.params.get("session_id")):
                raise HTTPException(409, "该会话正在回答，请稍后再发送")
            task = service().create(body.action, body.params)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return start(task)

    # Resource aliases share the same validated task submission path.
    def route(action):
        async def endpoint(params: dict):
            return await submit(TaskRequest(action=action, params=params))

        endpoint.__name__ = action.replace(".", "_")
        return endpoint

    for path, action in {
        "/papers/search": "papers.search",
        "/papers/related": "papers.related",
        "/papers/download": "papers.download",
        "/papers/map": "papers.map",
        "/documents/import": "documents.import",
        "/documents/open": "documents.open",
        "/chat/send": "chat.send",
        "/reading/ask": "reading.ask",
        "/knowledge/save": "knowledge.save",
        "/knowledge/search": "knowledge.search",
        "/knowledge/update": "knowledge.update",
        "/knowledge/review": "knowledge.review",
        "/knowledge/export": "knowledge.export",
        "/reports/generate": "reports.generate",
        "/slides/outline": "slides.outline",
        "/slides/build": "slides.build",
        "/slides/revise": "slides.revise",
    }.items():
        app.add_api_route(path, route(action), methods=["POST"], status_code=202)

    @app.get("/tasks")
    def tasks():
        return service().store.task_list()

    @app.get("/tasks/{task_id}")
    def status(task_id: str):
        try:
            return service().store.task_get(task_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post("/tasks/{task_id}/resume", status_code=202)
    async def resume(task_id: str):
        if len(running) >= service().settings.max_parallel_tasks:
            raise HTTPException(429, "正在执行的任务较多，请稍后恢复")
        task = status(task_id)
        if task["action"] == "chat.send":
            session = get_chat(task["params"]["session_id"])
            if session["pending_task_id"] and session["pending_task_id"] != task_id:
                raise HTTPException(409, "该会话正在回答，请稍后恢复")
            if session["revision"] != task["params"]["revision"] and not any(
                t["task_id"] == task_id for t in session["turns"]
            ):
                raise HTTPException(409, "会话已更新，请重新发送消息")
        if task["status"] in {"running", "completed"} or task_id in running:
            raise HTTPException(409, "任务已运行或完成")
        return start(task, resume=True)

    @app.get("/tasks/{task_id}/events")
    async def events(task_id: str, request: Request):
        status(task_id)

        async def stream():
            previous = None
            while not await request.is_disconnected():
                task = status(task_id)
                event = json.dumps(
                    {"status": task["status"], "stage": task["stage"], "error": task["error"]},
                    ensure_ascii=False,
                )
                if event != previous:
                    yield "data: " + event + "\n\n"
                    previous = event
                if task["status"] in {"completed", "failed", "interrupted"}:
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/tasks/{task_id}/artifacts/{filename}")
    def artifact(task_id: str, filename: str):
        status(task_id)
        directory = (service().settings.data_dir / "outputs" / task_id).resolve()
        path = (directory / filename).resolve()
        if path.parent != directory or not path.is_file():
            raise HTTPException(404, "产物不存在")
        return (
            FileResponse(path, filename=filename) if path.suffix == ".pdf" else FileResponse(path)
        )

    @app.get("/tasks/{task_id}/files")
    def files(task_id: str):
        status(task_id)
        directory = (service().settings.data_dir / "outputs" / task_id).resolve()
        return [
            p.name
            for p in sorted(directory.glob("*"))
            if p.is_file() and p.resolve().parent == directory
        ]

    @app.get("/records/{kind}")
    def records(kind: str):
        if kind not in {
            "paper",
            "document",
            "session",
            "knowledge",
            "report",
            "project",
            "library",
            "annotation",
            "idea",
            "experiment",
            "decision",
            "profile",
            "workspace_review",
            "reading_log",
            "personal_note",
        }:
            raise HTTPException(404, "未知记录类型")
        return service().store.list(kind)

    @app.get("/records/{kind}/{item_id}")
    def record(kind: str, item_id: str):
        try:
            return service().store.get(item_id, kind)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None

    @app.delete("/documents/{item_id}", status_code=202)
    async def delete_document(item_id: str):
        return await submit(TaskRequest(action="documents.delete", params={"id": item_id}))

    @app.delete("/knowledge/{item_id}", status_code=202)
    async def delete_knowledge(item_id: str):
        return await submit(TaskRequest(action="knowledge.delete", params={"id": item_id}))

    return app


app = create_app()
