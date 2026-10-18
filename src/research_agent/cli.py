import asyncio
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer

from .config import PROJECT_ROOT, get_settings
from .models import TaskRequest
from .workflows import Engine

app = typer.Typer(help="小知己：个人知识、记忆与科研工作台", no_args_is_help=True)
groups = {}
for name in (
    "papers",
    "documents",
    "reading",
    "knowledge",
    "reports",
    "slides",
    "tasks",
    "embeddings",
    "workspace",
    "backup",
    "memory",
):
    groups[name] = typer.Typer(no_args_is_help=True)
    app.add_typer(groups[name], name=name)


@app.callback()
def configure_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def show(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def execute(action, params):
    engine = Engine(get_settings())
    try:
        task = engine.create(action, params)
        typer.echo(f"任务 {task['id']}", err=True)
        result = asyncio.run(engine.run(task["id"]))
        show(result)
        if result["status"] != "completed":
            raise typer.Exit(1)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@groups["papers"].command("search")
def search(
    query: str,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
    sort: str = "relevance",
    mode: str = "auto",
    venue: Annotated[list[str] | None, typer.Option()] = None,
    publisher: str | None = None,
    include_claimed: bool = False,
):
    execute(
        "papers.search",
        dict(
            query=query,
            limit=limit,
            year_from=year_from,
            year_to=year_to,
            sort=sort,
            mode=mode,
            venues=venue or [],
            publisher=publisher,
            include_claimed=include_claimed,
        ),
    )


@groups["papers"].command("related")
def related(seed: str, limit: int = 50, offset: int = 0, similar_limit: int = 10):
    execute(
        "papers.related", dict(seed=seed, limit=limit, offset=offset, similar_limit=similar_limit)
    )


@groups["documents"].command("import")
def import_document(source: str, title: str | None = None, text_file: Path | None = None):
    execute(
        "documents.import",
        {
            "source": source,
            "title": title,
            "text": text_file.read_text(encoding="utf-8") if text_file else None,
        },
    )


@groups["documents"].command("delete")
def delete_document(document_id: str):
    execute("documents.delete", {"id": document_id})


@groups["documents"].command("list")
def documents():
    show(Engine(get_settings()).store.list("document"))


@groups["reading"].command("ask")
def ask(
    document_id: str,
    question: str,
    session: str | None = None,
    selection: str = "",
    page: int | None = None,
):
    execute(
        "reading.ask",
        {
            "document_id": document_id,
            "question": question,
            "session_id": session,
            "selection": selection,
            "page": page,
        },
    )


@groups["reading"].command("sessions")
def sessions():
    show(Engine(get_settings()).store.list("session"))


@groups["knowledge"].command("save")
def save(session_id: str, turn: int = -1, tag: Annotated[list[str] | None, typer.Option()] = None):
    execute("knowledge.save", {"session_id": session_id, "turn": turn, "tags": tag or []})


@groups["papers"].command("download")
def download_paper(paper_id: str):
    execute("papers.download", {"paper_id": paper_id})


@groups["papers"].command("map")
def paper_map(seed: str, limit: int = 20, candidate_limit: int = 24, sample_size: int = 50):
    """基于共引与文献耦合构建可追溯的相似图。"""
    execute(
        "papers.map",
        dict(seed=seed, limit=limit, candidate_limit=candidate_limit, sample_size=sample_size),
    )


@groups["knowledge"].command("search")
def knowledge_search(
    query: str,
    limit: int = 6,
    status: str | None = None,
    tag: str | None = None,
    document_id: str | None = None,
):
    execute(
        "knowledge.search",
        dict(query=query, limit=limit, status=status, tag=tag, document_id=document_id),
    )


@groups["knowledge"].command("update")
def knowledge_update(
    entry_id: str,
    revision: int,
    notes: str = "",
    status: str = "inbox",
    tag: Annotated[list[str] | None, typer.Option()] = None,
):
    """提交完整的批注、标签、状态；revision 使用当前卡片版本。"""
    execute(
        "knowledge.update",
        dict(id=entry_id, revision=revision, notes=notes, status=status, tags=tag or []),
    )


@groups["knowledge"].command("review")
def knowledge_review(days: int = 7):
    execute("knowledge.review", {"days": days})


@groups["knowledge"].command("export")
def knowledge_export():
    execute("knowledge.export", {})


@groups["knowledge"].command("delete")
def knowledge_delete(entry_id: str):
    execute("knowledge.delete", {"id": entry_id})


@groups["reports"].command("generate")
def generate(
    topic: str | None = None,
    kind: str = "research",
    days: int = 7,
    config: Path | None = None,
    limit: int = 30,
):
    params = json.loads(config.read_text(encoding="utf-8")) if config else {}
    if topic is not None:
        params["topic"] = topic
    params.setdefault("kind", kind)
    params.setdefault("days", days)
    params.setdefault("limit", limit)
    execute("reports.generate", params)


@groups["slides"].command("outline")
def outline(source: str, pages: int = 10):
    execute("slides.outline", {"source": source, "pages": pages})


@groups["slides"].command("build")
def build(deck_file: Path):
    execute("slides.build", {"deck": json.loads(deck_file.read_text(encoding="utf-8"))})


@groups["slides"].command("revise")
def revise(deck_file: Path, page: int, instruction: str):
    execute(
        "slides.revise",
        {
            "deck": json.loads(deck_file.read_text(encoding="utf-8")),
            "page": page,
            "instruction": instruction,
        },
    )


@groups["slides"].command("preview")
def preview(pptx: Path, output_dir: Path | None = None, renderer: str = "auto"):
    from .preview import render_preview

    try:
        show(render_preview(pptx, output_dir, renderer))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@groups["tasks"].command("status")
def status(task_id: str):
    show(Engine(get_settings()).store.task_get(task_id))


@groups["tasks"].command("list")
def task_list():
    show(Engine(get_settings()).store.task_list())


@groups["tasks"].command("resume")
def resume(task_id: str):
    engine = Engine(get_settings())
    task = engine.store.task_get(task_id)
    if task["status"] == "running":
        typer.echo("确认旧进程已停止后使用 tasks recover 清理中断状态。", err=True)
        raise typer.Exit(1)
    result = asyncio.run(engine.run(task_id, resume=True))
    show(result)
    if result["status"] != "completed":
        raise typer.Exit(1)


@groups["tasks"].command("recover")
def recover():
    """仅在旧进程已停止时，将残留 running 状态标记为 interrupted。"""
    Engine(get_settings()).interrupted_tasks()
    show({"recovered": True})


@groups["embeddings"].command("init")
def initialize_embeddings():
    from .embedding import Embedder

    show({"model_directory": Embedder(get_settings()).initialize()})


@groups["embeddings"].command("reindex")
def reindex():
    from .tools import Tools

    show(asyncio.run(Tools(get_settings()).documents.reindex()))


@app.command("run")
def run_request(request_file: Path):
    request = TaskRequest.model_validate_json(request_file.read_text(encoding="utf-8"))
    execute(request.action, request.params)


@groups["workspace"].command("submit")
def workspace_submit(action: str, params_file: Path):
    """提交项目工作空间操作，参数为 JSON 文件；例如 project.save、weekly。"""
    execute("workspace." + action, json.loads(params_file.read_text(encoding="utf-8")))


@groups["workspace"].command("stats")
def workspace_stats(project_id: str | None = None, days: int = 7):
    execute("workspace.stats", {"project_id": project_id, "days": days})


@groups["memory"].command("capture")
def memory_capture(
    text: str, notebook: str = "收件箱", category: str = "knowledge", layer: str = "context"
):
    execute(
        "memory.note.save",
        {"text": text, "notebook": notebook, "category": category, "layer": layer},
    )


@groups["memory"].command("search")
def personal_search(query: str, limit: int = 12):
    execute("memory.search", {"query": query, "limit": limit})


@groups["memory"].command("review")
def personal_review(days: int = 30):
    execute("memory.review", {"days": days})


@groups["memory"].command("export")
def personal_export():
    execute("memory.export", {})


@groups["workspace"].command("weekly")
def workspace_weekly(project_id: str | None = None, days: int = 7):
    execute("workspace.weekly", {"project_id": project_id, "days": days})


@groups["backup"].command("create")
def backup_create(destination: Path, offline: bool = False):
    """停服后备份数据库、归档材料和产物；不包含密钥、登录会话与模型权重。"""
    from .backup import create_backup

    if not offline:
        raise typer.BadParameter("请先停止工作台，再使用 --offline 明确离线备份")
    try:
        show(create_backup(get_settings().data_dir, destination))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


@groups["backup"].command("restore")
def backup_restore(archive: Path, offline: bool = False):
    """停服并重命名保留原 data 目录后，恢复到原绝对路径。"""
    from .backup import restore_backup

    if not offline:
        raise typer.BadParameter("请先停止工作台并保留原数据目录，再使用 --offline")
    try:
        show(restore_backup(archive, get_settings().data_dir))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


@app.command("serve")
def serve(port: int = 8000, host: str = "127.0.0.1"):
    import uvicorn

    settings = get_settings()
    if (
        host not in {"127.0.0.1", "localhost", "::1"}
        and len(settings.access_token.get_secret_value()) < 32
    ):
        raise typer.BadParameter("对外监听前必须配置至少 32 字符的 RESEARCH_ACCESS_TOKEN")
    uvicorn.run("research_agent.api:app", host=host, port=port)


@app.command("access-init")
def access_init():
    """创建随机私有访问令牌，保存到忽略文件；不向终端输出令牌。重启后生效。"""
    import secrets

    settings = get_settings()
    if settings.access_token.get_secret_value():
        show({"configured": True, "message": "已有访问令牌，未覆盖"})
        return
    target = settings.data_dir / "secrets" / "private-access.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(48)
    with target.open("x", encoding="utf-8") as output:
        output.write(token + "\n")
    with (PROJECT_ROOT / ".env").open("a", encoding="utf-8") as output:
        output.write("\nRESEARCH_ACCESS_TOKEN=" + token + "\n")
    show({"configured": True, "token_file": str(target), "restart_required": True})


@app.command("doctor")
def doctor(mcp: bool = False, model: bool = False):
    settings = get_settings()
    from .embedding import Embedder
    from .preview import libreoffice_path, powerpoint_available
    from .storage import Store

    store = Store(settings.data_dir)
    with store.connect() as db:
        db.execute("SELECT count(*) FROM fulltext").fetchone()
    checks = {
        "python": sys.version.split()[0],
        "database": str(store.path),
        "sqlite_fts5": True,
        "model_configured": settings.model_provider == "ollama"
        or bool(settings.model_api_key.get_secret_value()),
        "embedding_files": settings.embedding_dir.exists(),
        "node": shutil.which("node"),
        "ppt_dependency": (PROJECT_ROOT / "ppt/node_modules/pptxgenjs").exists(),
        "chrome": settings.chrome_path
        or next(
            (
                str(p)
                for p in [
                    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
                ]
                if p.exists()
            ),
            None,
        ),
        "libreoffice": libreoffice_path(),
        "powerpoint": powerpoint_available(),
        "private_access_enabled": bool(settings.access_token.get_secret_value()),
        "deployment_scope": "private_shared_workspace",
        "secure_cookies": settings.secure_cookies,
        "max_upload_bytes": settings.max_upload_bytes,
        "max_parallel_tasks": settings.max_parallel_tasks,
    }
    checks["versions"] = {
        p: importlib.metadata.version(p)
        for p in ("langgraph", "mcp", "fastapi", "sentence-transformers")
    }
    if settings.embedding_dir.exists():
        try:
            checks["embedding_dimension"] = len(Embedder(settings).encode(["科研助手"])[0])
        except Exception as exc:
            checks["embedding_error"] = type(exc).__name__
    if mcp:
        from .mcp_client import Gateway

        async def check():
            async with Gateway(settings).open() as gateway:
                if gateway.session:
                    return [t.name for t in (await gateway.session.list_tools()).tools]
                return ["local transport"]

        checks["mcp_tools"] = asyncio.run(check())
    if model:
        from .llm import Model
        from .models import GroundedAnswer

        try:
            checks["model_response"] = asyncio.run(
                Model(settings).generate("回答你好，evidence_ids 留空", {}, GroundedAnswer)
            ).answer
        except Exception as exc:
            checks["model_error"] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    show(checks)


if __name__ == "__main__":
    app()
