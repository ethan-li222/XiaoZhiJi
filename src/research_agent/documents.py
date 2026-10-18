import asyncio
import hashlib
import io
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup, UnicodeDammit

from .memory import knowledge_text
from .models import DocumentChunk, ReadingSession


class DocumentTools:
    def __init__(self, settings, store, net, embedder):
        self.settings, self.store, self.net, self.embedder = settings, store, net, embedder

    async def browser_text(self, url):
        from .mcp_client import browser_session

        async with browser_session(self.settings) as session:
            navigation = await session.call_tool("browser_navigate", {"url": url})
            if navigation.isError:
                details = " ".join(c.text for c in navigation.content if hasattr(c, "text"))
                raise ValueError("Chrome 无法打开文章：" + details[:1200])
            result = await session.call_tool(
                "browser_evaluate",
                {"function": "() => ({title: document.title, text: document.body.innerText})"},
            )
            if result.isError:
                raise ValueError("Chrome 正文提取失败")
            if result.structuredContent and "text" in result.structuredContent:
                return result.structuredContent
            text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
            start = text.find("{")
            if start < 0:
                raise ValueError("Chrome 返回格式无法解析，请使用文本导入")
            try:
                body, _ = json.JSONDecoder().raw_decode(text[start:])
                if not isinstance(body.get("text"), str):
                    raise ValueError("Chrome 返回正文格式无效")
                return body
            except (ValueError, AttributeError):
                raise ValueError("Chrome 返回格式无法解析，请使用文本导入") from None

    async def import_document(self, source: str, text: str | None = None, title=None, **_):
        warnings, pages = [], []
        pdf_bytes = None
        if text is not None:
            pages = [(None, text)]
            title = title or "导入文本"
        elif source.startswith(("https://", "http://")):
            try:
                raw = await self.net.get(source, binary=True)
            except ValueError:
                if not self.settings.browser_enabled:
                    raise
                raw = None
            if raw is not None and raw.lstrip().startswith(b"%PDF"):
                pdf_bytes = raw
                pages = self.pdf_pages(io.BytesIO(raw))
                title = title or source.rsplit("/", 1)[-1]
            else:
                import trafilatura

                html = UnicodeDammit(raw).unicode_markup if raw else ""
                extracted = trafilatura.extract(html, include_tables=True) if html else None
                soup = BeautifulSoup(html or "", "html.parser")
                title = title or (soup.title.get_text().strip() if soup.title else None)
                if not extracted and self.settings.browser_enabled:
                    body = await self.browser_text(source)
                    extracted, title = body["text"], title or body["title"]
                if not extracted:
                    raise ValueError("未获取到正文；可启用 Chrome MCP 或提供 text 导入")
                title = title or source
                pages = [(None, extracted)]
        else:
            path = Path(source).resolve()
            title = title or path.stem
            if path.suffix.lower() == ".pdf":
                pdf_bytes = path.read_bytes()
                pages = self.pdf_pages(path)
            elif path.suffix.lower() in {".md", ".txt"}:
                pages = [(None, path.read_text(encoding="utf-8"))]
            else:
                raise ValueError("文件格式只支持 PDF、Markdown、TXT")
            source = str(path)
        if not any(t.strip() for _, t in pages):
            raise ValueError("文章正文为空")
        digest = hashlib.sha256((source + "\n" + str(pages)).encode()).hexdigest()[:24]
        document_id = "doc-" + digest
        chunks, section = [], ""
        for page, content in pages:
            # Preserve Markdown heading and paragraph locations. Long paragraphs overlap.
            for n, para in enumerate(re.split(r"\n\s*\n", content), 1):
                para = para.strip()
                if not para:
                    continue
                if para.startswith("#"):
                    section = para.splitlines()[0].lstrip("# ")
                for start in range(0, len(para), 650):
                    chunks.append(
                        DocumentChunk(
                            id=f"{document_id}-{len(chunks)}",
                            document_id=document_id,
                            text=para[start : start + 800],
                            source=source,
                            title=title,
                            page=page,
                            section=section,
                            paragraph=n,
                        ).model_dump()
                    )
        vectors = None
        try:
            vectors = await asyncio.to_thread(self.embedder.encode, [c["text"] for c in chunks])
        except (ValueError, OSError) as exc:
            warnings.append(str(exc))
        document = {"id": document_id, "source": source, "title": title, "chunks": len(chunks)}
        if pdf_bytes is not None:
            document["page_count"] = len(pages)
            directory = self.settings.data_dir / "documents"
            directory.mkdir(parents=True, exist_ok=True)
            pdf_path = directory / (document_id + ".pdf")
            pdf_path.write_bytes(pdf_bytes)
            document["pdf_path"] = str(pdf_path)
        self.store.put("document", document)
        for i, chunk in enumerate(chunks):
            self.store.put(
                "chunk",
                chunk,
                parent=document_id,
                text=chunk["text"],
                vector=vectors[i] if vectors else None,
                model=self.embedder.identity if vectors else None,
            )
        return {"document": self.store.get(document_id), "warnings": warnings}

    @staticmethod
    def pdf_pages(source):
        from pypdf import PdfReader

        reader = PdfReader(source)
        pages = [(n, p.extract_text() or "") for n, p in enumerate(reader.pages, 1)]
        if not any(t.strip() for _, t in pages):
            raise ValueError("PDF 无可提取文本，可能为扫描件；首版不包含 OCR")
        return pages

    async def retrieve(self, document_id, question, session_id=None, selection="", page=None, **_):
        self.store.get(document_id, "document")
        warnings, vector = [], None
        if session_id:
            session = ReadingSession.model_validate(self.store.get(session_id, "session"))
            if session.document_id != document_id:
                raise ValueError("阅读会话绑定了另一篇文章，请新建会话")
        else:
            session = ReadingSession(document_id=document_id)
            self.store.put("session", session.model_dump(), parent=document_id)
        query = " ".join(
            [question, selection[:1500], *[h["question"][:300] for h in session.history[-2:]]]
        )
        try:
            vector = (await asyncio.to_thread(self.embedder.encode, [query], True))[0]
        except (ValueError, OSError) as exc:
            warnings.append(str(exc))
        if page is not None:
            evidence = [c for c in self.store.list("chunk", document_id) if c["page"] == page][:6]
        else:
            evidence = self.store.search(
                query, parent=document_id, vector=vector, model=self.embedder.identity
            )
        if selection:
            # Locate actual matching source text; never trust a pasted selection as evidence.
            matches = [
                c
                for c in self.store.list("chunk", document_id)
                if selection in c["text"] and (page is None or c["page"] == page)
            ]
            evidence = list({c["id"]: c for c in matches[:2] + evidence}.values())[:6]
            if not matches:
                warnings.append("选段未在已导入正文中精确定位，使用检索上下文")
        memories = self.store.search(query, "knowledge", status="confirmed", limit=3)
        history = [
            {"question": h["question"][:500], "answer": h["answer"][:1200]}
            for h in session.history[-6:]
        ]
        topics = " / ".join(h["question"][:120] for h in session.history[:-6][-10:])
        return {
            "evidence": evidence,
            "session": session.model_dump(),
            "warnings": warnings,
            "reading_history": history,
            "earlier_topics": topics,
            "memories": [
                {
                    "id": k["id"],
                    "question": k["question"][:500],
                    "answer": k["answer"][:1200],
                    "notes": k.get("notes", "")[:800],
                    "document_id": k["document_id"],
                }
                for k in memories
            ],
        }

    async def search_knowledge(self, query, limit=6, status=None, tag=None, document_id=None, **_):
        if not query.strip() or not 1 <= limit <= 30:
            raise ValueError("query 不能为空，limit 为 1–30")
        warnings, vector = [], None
        try:
            vector = (await asyncio.to_thread(self.embedder.encode, [query], True))[0]
        except (ValueError, OSError) as exc:
            warnings.append(str(exc))
        return {
            "entries": self.store.search(
                query,
                "knowledge",
                vector=vector,
                model=self.embedder.identity,
                limit=limit,
                status=status,
                tag=tag,
                parent=document_id,
            ),
            "warnings": warnings,
        }

    async def save_knowledge(self, session_id, turn=-1, tags=None, entry_id=None, **_):
        from .models import KnowledgeEntry

        session = self.store.get(session_id, "session")
        try:
            qa = session["history"][turn]
        except IndexError:
            raise ValueError("该会话还没有可保存的问答") from None
        # Recognize pre-migration IDs without rewriting or overwriting curated records.
        for old_turn in {
            -1,
            turn,
            turn % len(session["history"]),
            turn % len(session["history"]) - len(session["history"]),
        }:
            old_id = (
                "kb-"
                + hashlib.sha256((session_id + str(old_turn) + str(qa)).encode()).hexdigest()[:24]
            )
            try:
                old_entry = self.store.get(old_id, "knowledge")
                return {"entry": old_entry, "warnings": []}
            except ValueError:
                pass
        entry = KnowledgeEntry(
            id=entry_id
            or "kb-"
            + hashlib.sha256(
                (session_id + ":" + str(turn % len(session["history"]))).encode()
            ).hexdigest()[:24],
            session_id=session_id,
            turn_index=turn % len(session["history"]),
            question=qa["question"],
            answer=qa["answer"],
            selection=qa.get("selection", ""),
            document_id=session["document_id"],
            evidence=qa["evidence"],
            tags=tags or [],
        ).model_dump()
        text = knowledge_text(entry)
        vector, warnings = None, []
        try:
            vector = (await asyncio.to_thread(self.embedder.encode, [text]))[0]
        except (ValueError, OSError) as exc:
            warnings.append(str(exc))
        entry = self.store.put(
            "knowledge",
            entry,
            if_absent=True,
            parent=entry["document_id"],
            text=text,
            vector=vector,
            model=self.embedder.identity if vector else None,
        )
        return {"entry": entry, "warnings": warnings}

    async def reindex(self):
        count = 0
        for kind in ("chunk", "knowledge"):
            items = self.store.list(kind)
            for i in range(0, len(items), 32):
                batch = items[i : i + 32]
                texts = [x["text"] if kind == "chunk" else knowledge_text(x) for x in batch]
                vectors = await asyncio.to_thread(self.embedder.encode, texts)
                for item, text, vector in zip(batch, texts, vectors):
                    self.store.put(
                        kind,
                        item,
                        parent=item["document_id"],
                        text=text,
                        vector=vector,
                        model=self.embedder.identity,
                    )
                    count += 1
        return {"indexed": count}
