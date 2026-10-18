from .chat import ChatContext
from .documents import DocumentTools
from .embedding import Embedder
from .memory import MemoryTools
from .network import Network
from .papers import PaperTools
from .personal_memory import PersonalMemory
from .reports import ReportTools
from .requests import validate_params
from .storage import Store
from .workspace import WorkspaceTools


class Tools:
    """Business tools shared by MCP servers and the in-process test transport."""

    def __init__(self, settings, client=None, embedder=None):
        self.settings = settings
        self.store = Store(settings.data_dir)
        self.embedder = embedder or Embedder(settings)
        self.net = Network(settings, self.store, client)
        self.papers = PaperTools(settings, self.store, self.net, self.embedder)
        self.documents = DocumentTools(settings, self.store, self.net, self.embedder)
        self.memory = MemoryTools(self.store, self.embedder)
        self.personal = PersonalMemory(self.store, self.embedder)
        self.reports = ReportTools(self.papers, self.net)
        self.workspace = WorkspaceTools(settings, self.store, self.papers, self.documents)

    async def call(self, action, params):
        if action != "slides.build":
            params = validate_params(action, params)
        if action.startswith("workspace."):
            return await self.workspace.call(action, params)
        if action.startswith("memory."):
            return await self.personal.call(action, params)
        if action == "chat.send":
            return await ChatContext(self.store, self.embedder).prepare(**params)
        if action == "papers.search":
            return await self.papers.search(**params)
        if action == "papers.related":
            return await self.papers.related(**params)
        if action == "papers.download":
            return await self.papers.download(**params)
        if action == "papers.map":
            from .bibliometrics import LiteratureMap

            return await LiteratureMap(
                self.papers, params["sample_size"], params["candidate_limit"]
            ).build(params["seed"], params["limit"])
        if action == "documents.import":
            return await self.documents.import_document(**params)
        if action == "documents.open":
            import hashlib
            from pathlib import Path

            paper = self.store.get(params["paper_id"], "paper")
            existing = next(
                (d for d in self.store.list("document") if d.get("paper_id") == paper["id"]), None
            )
            if existing:
                return {"document": existing, "warnings": []}
            path = (
                self.settings.data_dir
                / "paper-downloads"
                / (hashlib.sha256(paper["id"].encode()).hexdigest()[:24] + ".pdf")
            )
            if not path.is_file():
                path = Path((await self.papers.download(paper["id"]))["pdf_path"])
            result = await self.documents.import_document(str(path), title=paper["title"])
            result["document"].update(paper_id=paper["id"], source_url=paper.get("url", ""))
            self.store.put("document", result["document"])
            return result
        if action == "reading.ask":
            return await self.documents.retrieve(**params)
        if action == "knowledge.save":
            return await self.documents.save_knowledge(**params)
        if action == "knowledge.search":
            return await self.documents.search_knowledge(**params)
        if action in {"knowledge.update", "knowledge.review", "knowledge.export"}:
            return await getattr(self.memory, action.split(".")[1])(**params)
        if action == "reports.generate":
            return await self.reports.collect(**params)
        if action in {"documents.delete", "knowledge.delete"}:
            kind = "document" if action == "documents.delete" else "knowledge"
            self.store.get(params["id"], kind)
            self.store.delete(params["id"])
            return {"deleted": params["id"]}
        if action == "slides.build":
            from pathlib import Path

            from .slides import render_deck

            deck = validate_params(action, {"deck": params["deck"]})["deck"]
            output = Path(params["output"]).resolve()
            if not output.is_relative_to(self.settings.data_dir / "outputs"):
                raise ValueError("PPT 输出必须位于项目数据目录的 outputs 下")
            return await render_deck(deck, output)
        raise ValueError("不支持的工具操作：" + action)
