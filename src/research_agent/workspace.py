"""Project-centered reading, evidence, ideas and experimental planning."""

import hashlib
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from .models import new_id, now
from .workspace_models import Annotation, Experiment, Idea, LibraryItem, Project


class WorkspaceTools:
    def __init__(self, settings, store, papers, documents):
        self.settings, self.store, self.papers, self.documents = settings, store, papers, documents

    async def call(self, action, params):
        handlers = {
            "project.save": self.project_save,
            "library.add": self.library_add,
            "library.update": self.library_update,
            "library.acquire": self.library_acquire,
            "import": self.import_material,
            "annotation.save": self.annotation_save,
            "idea.save": self.idea_save,
            "experiment.save": self.experiment_save,
            "reading.log": self.reading_log,
            "profile.save": self.profile_save,
            "decision.save": self.decision_save,
        }
        operation = action.removeprefix("workspace.")
        if operation in handlers:
            return await handlers[operation](**params)
        from .workspace_insights import WorkspaceInsights

        return await getattr(WorkspaceInsights(self), operation)(**params)

    def project(self, project_id):
        return self.store.get(project_id, "project")

    def in_project(self, project_id, document_id):
        self.project(project_id)
        self.store.get(document_id, "document")
        if not any(
            k.get("document_id") == document_id and k["project_id"] == project_id
            for k in self.store.list("library")
        ):
            raise ValueError("该文档尚未加入此项目材料库，请先归档材料")

    def source(self, identifier, project_id):
        for kind in ("annotation", "knowledge", "personal_note", "library"):
            try:
                record = self.store.get(identifier, kind)
                break
            except ValueError:
                continue
        else:
            raise ValueError("来源笔记或材料不存在：" + identifier)
        if kind in {"annotation", "library"} and record["project_id"] != project_id:
            raise ValueError("证据属于另一个项目")
        doc_id = record.get("document_id")
        if not doc_id:
            raise ValueError("证据材料尚未导入阅读，请先下载并导入")
        self.in_project(project_id, doc_id)
        document = self.store.get(doc_id, "document")
        if kind in {"annotation", "personal_note"}:
            if kind == "personal_note" and record["status"] != "confirmed":
                raise ValueError("阅读批注须先核对并设为已确认，才能作为研究证据")
            for chunk_id in record.get("evidence_ids", []):
                chunk = self.store.get(chunk_id, "chunk")
                if chunk["document_id"] != doc_id:
                    raise ValueError("批注原文来源不匹配")
            text = "个人笔记：" + record["text"] + "\n选段：" + record.get("selection", "")
        elif kind == "knowledge":
            if record.get("status", "inbox") != "confirmed":
                raise ValueError("知识卡片须先核对并设为已确认，才能作为研究证据")
            text = (
                record["question"]
                + "\n"
                + record["answer"]
                + "\n个人批注："
                + record.get("notes", "")
            )
        else:
            text = "\n".join(c["text"] for c in self.store.list("chunk", doc_id)[:4])
        return {
            "id": identifier,
            "title": document["title"],
            "url": document.get("source_url") or document["source"],
            "text": text[:5000],
            "document_id": doc_id,
            "kind": kind,
            "created_at": record.get("created_at"),
            "project_id": project_id,
        }

    def save(self, kind, params, *, model=None, identifier=None, parent=None, verb=None):
        params = dict(params)
        operation_id = params.pop("operation_id", None)
        identifier = identifier or params.pop("id", None)
        supplied_revision = params.pop("revision", None)
        old = None
        if identifier:
            try:
                old = self.store.get(identifier, kind)
            except ValueError:
                if supplied_revision is not None:
                    raise
        if old and supplied_revision is None:
            raise ValueError("修改记录需要当前 revision，请刷新后重试")
        if not identifier:
            identifier = (
                kind
                + "-"
                + (
                    hashlib.sha256(operation_id.encode()).hexdigest()[:24]
                    if operation_id
                    else new_id()
                )
            )
        # Idempotent operation checks occur in the same transaction as the write/event.
        entry = {
            **(old or {}),
            **params,
            "id": identifier,
            "created_at": (old or {}).get("created_at", now()),
            "updated_at": now(),
            "revision": (supplied_revision or 0) + 1,
        }
        if old and entry.get("project_id") != old.get("project_id"):
            raise ValueError("不能通过修改把记录移动到另一个项目")
        if model:
            entry = model.model_validate(entry).model_dump()
        event = {
            "id": "event-" + (operation_id or new_id()),
            "occurred_at": now(),
            "project_id": entry.get("project_id", identifier if kind == "project" else None),
            "record_id": identifier,
            "kind": kind,
            "verb": verb or ("updated" if old else "created"),
            "status": entry.get("status"),
            "previous_status": (old or {}).get("status"),
            "actor": "user",
        }
        entry = self.store.put(
            kind,
            entry,
            parent=parent,
            expected_revision=supplied_revision if old else None,
            operation_id=operation_id,
            event=event,
        )
        return {"entry": entry}

    async def project_save(self, **params):
        if not params["name"].strip():
            raise ValueError("项目名称不能为空白")
        return self.save("project", params, model=Project)

    async def library_add(
        self,
        project_id,
        paper_id=None,
        document_id=None,
        kind="paper",
        tags=None,
        operation_id=None,
    ):
        self.project(project_id)
        if paper_id:
            paper = self.store.get(paper_id, "paper")
            title, source = paper["title"], paper["url"]
            venue, year = paper.get("venue") or "", paper.get("year")
        else:
            document = self.store.get(document_id, "document")
            title, source, venue, year = document["title"], document["source"], "", None
        if document_id:
            self.store.get(document_id, "document")
        identifier = (
            "library-"
            + hashlib.sha256((project_id + ":" + (paper_id or document_id)).encode()).hexdigest()[
                :24
            ]
        )
        try:
            return {"entry": self.store.get(identifier, "library"), "duplicate": True}
        except ValueError:
            pass
        return self.save(
            "library",
            dict(
                project_id=project_id,
                kind=kind,
                title=title,
                paper_id=paper_id,
                document_id=document_id,
                source_url=source,
                venue=venue,
                year=year,
                tags=tags or [],
                operation_id=operation_id,
            ),
            model=LibraryItem,
            identifier=identifier,
            parent=project_id,
        )

    async def library_update(
        self,
        id,
        revision,
        status,
        tags,
        venue="",
        organization="",
        source_status="unverified",
        operation_id=None,
    ):
        old = self.store.get(id, "library")
        data = {
            **old,
            "revision": revision,
            "status": status,
            "tags": tags,
            "venue": venue,
            "organization": organization,
            "source_status": source_status,
            "operation_id": operation_id,
        }
        if status == "read" and old["status"] != "read":
            data["completed_at"] = now()
        if status != "read":
            data["completed_at"] = None
        return self.save(
            "library",
            data,
            model=LibraryItem,
            parent=old["project_id"],
            verb="status_changed" if status != old["status"] else "updated",
        )

    async def library_acquire(self, id, operation_id=None):
        item = self.store.get(id, "library")
        self.project(item["project_id"])
        if item.get("document_id"):
            self.store.get(item["document_id"], "document")
            return {"entry": item, "document": self.store.get(item["document_id"]), "warnings": []}
        if not item.get("paper_id"):
            raise ValueError("此材料没有可下载的论文标识")
        result = await self.papers.download(item["paper_id"])
        category = re.sub(r"[^\w-]", "_", item.get("venue") or "unverified")[:60]
        directory = (
            self.settings.data_dir
            / "library"
            / item["project_id"]
            / ("venue-" + category + "-" + str(item.get("year") or "unknown"))
            / id
        ).resolve()
        if not directory.is_relative_to((self.settings.data_dir / "library").resolve()):
            raise ValueError("材料归档路径无效")
        directory.mkdir(parents=True, exist_ok=True)
        pdf = directory / "paper.pdf"
        shutil.copyfile(result["pdf_path"], pdf)
        imported = await self.documents.import_document(str(pdf), title=item["title"])
        document = imported["document"]
        document["source_url"] = item["source_url"]
        self.store.put("document", document)
        data = {
            **item,
            "document_id": document["id"],
            "pdf_path": str(pdf),
            "operation_id": operation_id,
        }
        saved = self.save(
            "library", data, model=LibraryItem, parent=item["project_id"], verb="acquired"
        )
        from .exports import write_json

        write_json(directory / "metadata.json", saved["entry"])
        return {
            **saved,
            "document": document,
            "warnings": result["warnings"] + imported["warnings"],
        }

    async def import_material(
        self,
        project_id,
        source,
        title=None,
        text=None,
        kind="industry",
        organization="",
        published_at=None,
        operation_id=None,
    ):
        self.project(project_id)
        if operation_id:
            with self.store.connect() as db:
                row = db.execute(
                    "SELECT item_id FROM operations WHERE id=?", (operation_id,)
                ).fetchone()
            if row:
                entry = self.store.get(row[0], "library")
                return {
                    "entry": entry,
                    "document": self.store.get(entry["document_id"], "document"),
                    "warnings": [],
                }
        if published_at:
            from datetime import date

            date.fromisoformat(published_at[:10])
        imported = await self.documents.import_document(source, title=title, text=text)
        document = imported["document"]
        document.update(source_url=source, published_at=published_at)
        self.store.put("document", document)
        saved = await self.library_add(
            project_id,
            document_id=document["id"],
            kind=kind,
            operation_id=(operation_id + ":add") if operation_id else None,
        )
        item = saved["entry"]
        # A retry can find the initial library entry before metadata was committed.
        if not saved.get("duplicate") or operation_id:
            hostname = urlparse(source).hostname or ""
            domains = (
                "openai.com",
                "anthropic.com",
                "research.google",
                "deepmind.google",
                "microsoft.com",
                "huggingface.co",
                "nvidia.com",
                "engineering.fb.com",
                "ai.meta.com",
            )
            official = any(hostname == host or hostname.endswith("." + host) for host in domains)
            data = {
                **item,
                "organization": organization,
                "published_at": published_at,
                "source_status": "official_domain" if official else "unverified",
                "operation_id": operation_id,
            }
            local = Path(source)
            if (
                not source.startswith(("http://", "https://"))
                and local.is_file()
                and local.suffix.lower() == ".pdf"
            ):
                directory = (
                    self.settings.data_dir / "library" / project_id / "uploaded" / item["id"]
                )
                directory = directory.resolve()
                if not directory.is_relative_to((self.settings.data_dir / "library").resolve()):
                    raise ValueError("材料归档路径无效")
                directory.mkdir(parents=True, exist_ok=True)
                pdf = directory / "paper.pdf"
                shutil.copyfile(local, pdf)
                data["pdf_path"] = str(pdf)
            saved = self.save("library", data, model=LibraryItem, parent=project_id)
        return {**saved, "document": document, "warnings": imported["warnings"]}

    async def annotation_save(self, **params):
        self.in_project(params["project_id"], params["document_id"])
        selection, page = params["selection"].strip(), params.get("page")
        chunks = self.store.list("chunk", params["document_id"])
        matches = [
            c
            for c in chunks
            if (page is None or c["page"] == page) and selection and selection in c["text"]
        ]
        if selection and not matches:
            raise ValueError("选段未在指定原文或页码中找到，请重新选择原文")
        if not params["text"].strip():
            raise ValueError("批注内容不能为空白")
        params.update(selection=selection, evidence_ids=[c["id"] for c in matches[:3]])
        return self.save("annotation", params, model=Annotation, parent=params["document_id"])

    async def idea_save(self, **params):
        self.project(params["project_id"])
        for identifier in params["source_ids"]:
            self.source(identifier, params["project_id"])
        if params["status"] in {"ready", "testing", "supported"} and not params["source_ids"]:
            raise ValueError("进入验证阶段前，请关联至少一条已核对的笔记或材料")
        return self.save("idea", params, model=Idea, parent=params["project_id"])

    async def experiment_save(self, **params):
        idea = self.store.get(params["idea_id"], "idea")
        self.project(idea["project_id"])
        for identifier in idea["source_ids"]:
            self.source(identifier, idea["project_id"])
        if params["status"] == "completed" and not params["actual_result"].strip():
            raise ValueError("完成实验需要填写实际结果，不能将预期结果当作实际结果")
        params["project_id"] = idea["project_id"]
        return self.save("experiment", params, model=Experiment, parent=idea["id"])

    async def reading_log(self, id, minutes, reflection="", operation_id=None):
        item = self.store.get(id, "library")
        self.project(item["project_id"])
        return self.save(
            "reading_log",
            dict(
                library_id=id,
                project_id=item["project_id"],
                minutes=minutes,
                reflection=reflection,
                operation_id=operation_id,
            ),
            parent=id,
            verb="reading_logged",
        )

    async def profile_save(
        self, goal, stage="", constraints="", weekly_hours=None, operation_id=None
    ):
        try:
            old = self.store.get("workspace-profile", "profile")
        except ValueError:
            old = {}
        return self.save(
            "profile",
            dict(
                goal=goal,
                stage=stage,
                constraints=constraints,
                weekly_hours=weekly_hours,
                revision=old.get("revision"),
                operation_id=operation_id,
            ),
            identifier="workspace-profile",
        )

    async def decision_save(self, **params):
        self.project(params["project_id"])
        for identifier in params["evidence_ids"]:
            self.source(identifier, params["project_id"])
        if params.get("review_date"):
            from datetime import date

            date.fromisoformat(params["review_date"])
        return self.save("decision", params, parent=params["project_id"])
