import asyncio
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from .models import Paper, PaperRelation
from .venues import PORTALS, canonical_venue, matches_venue, venue_metadata


def normalize_doi(value):
    return (
        re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", value or "", flags=re.I).lower().strip()
        or None
    )


def from_openalex(item):
    inv = item.get("abstract_inverted_index") or {}
    words = sorted((p, word) for word, positions in inv.items() for p in positions)
    loc = item.get("best_oa_location") or {}
    ids = item.get("ids") or {}
    arxiv = re.search(r"arxiv\.org/(?:abs|pdf)/([^?#]+)", loc.get("landing_page_url") or "")
    primary = (item.get("primary_location") or {}).get("source") or {}
    return Paper(
        id=item["id"],
        title=item.get("title") or "无标题",
        authors=[a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])],
        year=item.get("publication_year"),
        published_at=item.get("publication_date"),
        doi=normalize_doi(ids.get("doi")),
        arxiv_id=arxiv[1].removesuffix(".pdf") if arxiv else None,
        abstract=" ".join(w for _, w in words),
        url=ids.get("doi") or item["id"],
        pdf_url=loc.get("pdf_url"),
        citation_count=item.get("cited_by_count", 0),
        source_ids={"openalex": item["id"]},
        **venue_metadata(
            primary.get("display_name", ""), publisher=primary.get("host_organization_name", "")
        ),
    )


def from_semantic(item):
    ids = item.get("externalIds") or {}
    return Paper(
        id="S2:" + item["paperId"],
        title=item.get("title") or "无标题",
        authors=[a.get("name", "") for a in item.get("authors", [])],
        year=item.get("year"),
        published_at=item.get("publicationDate"),
        doi=normalize_doi(ids.get("DOI")),
        arxiv_id=ids.get("ArXiv"),
        abstract=item.get("abstract") or "",
        url=item.get("url") or "https://www.semanticscholar.org/paper/" + item["paperId"],
        pdf_url=(item.get("openAccessPdf") or {}).get("url"),
        citation_count=item.get("citationCount", 0),
        source_ids={"semantic": item["paperId"]},
        **venue_metadata(
            (item.get("publicationVenue") or {}).get("name") or item.get("venue") or ""
        ),
    )


def deduplicate(papers):
    result, aliases = [], {}

    def merge(existing, paper):
        existing.source_ids.update(paper.source_ids)
        existing.abstract = existing.abstract or paper.abstract
        existing.pdf_url = existing.pdf_url or paper.pdf_url
        existing.doi = existing.doi or paper.doi
        existing.arxiv_id = existing.arxiv_id or paper.arxiv_id
        existing.authors = existing.authors or paper.authors
        existing.year = existing.year or paper.year
        existing.published_at = existing.published_at or paper.published_at
        existing.citation_count = max(existing.citation_count, paper.citation_count)
        if paper.venue_status == "indexed" or existing.venue_status == "unknown":
            existing.venue, existing.venue_status = paper.venue, paper.venue_status
            existing.venue_claim = paper.venue_claim or existing.venue_claim
        existing.publisher = existing.publisher or paper.publisher

    for paper in papers:
        keys = [paper.id]
        if paper.doi:
            keys.append("doi:" + paper.doi)
        if paper.arxiv_id:
            keys.append("arxiv:" + re.sub(r"v\d+$", "", paper.arxiv_id))
        matches = {aliases[k] for k in keys if k in aliases}
        if matches:
            idx = min(matches)
            existing = result[idx]
            for other in matches - {idx}:
                merge(existing, result[other])
                result[other] = None
                for key, value in list(aliases.items()):
                    if value == other:
                        aliases[key] = idx
            merge(existing, paper)
        else:
            idx = len(result)
            result.append(paper)
        for key in keys:
            aliases[key] = idx
    return [p for p in result if p is not None]


class PaperTools:
    def __init__(self, settings, store, network, embedder):
        self.settings, self.store, self.net, self.embedder = settings, store, network, embedder
        from .browser_papers import BrowserPaperSearch

        self.browser = BrowserPaperSearch(settings)

    async def oa(self, suffix="", params=None):
        params = dict(params or {})
        key = self.settings.openalex_api_key.get_secret_value()
        if key:
            params["api_key"] = key
        return await self.net.get("https://api.openalex.org/works" + suffix, params)

    async def s2(self, suffix, params=None):
        key = self.settings.semantic_scholar_api_key.get_secret_value()
        return await self.net.get(
            "https://api.semanticscholar.org/graph/v1/paper/" + suffix,
            params,
            {"x-api-key": key} if key else {},
            interval=1.0,
        )

    async def search(
        self,
        query: str,
        limit=20,
        year_from=None,
        year_to=None,
        sort="relevance",
        publication_from=None,
        publication_to=None,
        mode="auto",
        venues=None,
        publisher=None,
        include_claimed=False,
        **_,
    ):
        if not query.strip() or not 1 <= limit <= 100:
            raise ValueError("关键词不能为空，limit 必须为 1–100")
        if sort not in {"relevance", "date", "citations"}:
            raise ValueError("sort 应为 relevance、date 或 citations")
        if year_from and year_to and year_from > year_to:
            raise ValueError("起始年份不能晚于结束年份")
        papers, warnings, browser_result = [], [], {}
        requested_limit = limit
        limit = min(100, limit * 3) if venues or publisher else limit
        if mode in {"browser", "arxiv_browser", "google_research_browser"}:
            site = {
                "browser": "both",
                "arxiv_browser": "arxiv",
                "google_research_browser": "google_research",
            }[mode]
            browser_result = await self.browser.search(query, limit, site, sort, year_from, year_to)
            papers = [Paper.model_validate(p) for p in browser_result["papers"]]
            return self.finish_search(
                papers,
                browser_result.get("warnings", []),
                requested_limit,
                sort,
                year_from,
                year_to,
                browser_result,
                venues,
                publisher,
                include_claimed,
            )
        params = {"search": query, "per-page": limit}
        filters = []
        if publication_from:
            filters.append(f"from_publication_date:{publication_from}")
        elif year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if publication_to:
            filters.append(f"to_publication_date:{publication_to}")
        elif year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if sort != "relevance":
            params["sort"] = {"date": "publication_date:desc", "citations": "cited_by_count:desc"}[
                sort
            ]
        try:
            body = await self.oa(params=params)
            papers.extend(from_openalex(i) for i in body["results"])
        except ValueError as exc:
            warnings.append(str(exc))
        try:
            arxiv_query = "all:" + query
            if publication_from and publication_to:
                start_date = publication_from.replace("-", "") + "0000"
                end_date = publication_to.replace("-", "") + "2359"
                arxiv_query = f"({arxiv_query}) AND submittedDate:[{start_date} TO {end_date}]"
            params = {
                "search_query": arxiv_query,
                "start": 0,
                "max_results": limit,
                "sortBy": "submittedDate" if sort == "date" else "relevance",
                "sortOrder": "descending",
            }
            xml = await self.net.get(
                "https://export.arxiv.org/api/query", params, json_response=False, interval=3
            )
            ns = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}
            for e in ET.fromstring(xml).findall("a:entry", ns):
                url = e.findtext("a:id", "", ns)
                if "/abs/" not in url:
                    continue
                date = e.findtext("a:published", "", ns)
                year = int(date[:4]) if date else None
                if year and ((year_from and year < year_from) or (year_to and year > year_to)):
                    continue
                arxiv_id = url.split("/abs/")[-1]
                papers.append(
                    Paper(
                        id="arxiv:" + arxiv_id,
                        title=" ".join(e.findtext("a:title", "", ns).split()),
                        authors=[a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)],
                        year=year,
                        published_at=date,
                        doi=normalize_doi(e.findtext("ar:doi", "", ns)),
                        arxiv_id=arxiv_id,
                        abstract=e.findtext("a:summary", "", ns).strip(),
                        url=url,
                        pdf_url="https://arxiv.org/pdf/" + arxiv_id,
                        source_ids={"arxiv": arxiv_id},
                        **venue_metadata(
                            claims=e.findtext("ar:comment", "", ns)
                            + " "
                            + e.findtext("ar:journal_ref", "", ns)
                        ),
                    )
                )
        except (ValueError, ET.ParseError) as exc:
            warnings.append(str(exc))
        if (
            mode == "auto"
            and self.settings.browser_enabled
            and (not papers or any("HTTP 429" in w for w in warnings))
        ):
            try:
                browser_result = await self.browser.search(
                    query, limit, "both", sort, year_from, year_to
                )
                extra = [Paper.model_validate(p) for p in browser_result["papers"]]
                if publication_from or publication_to:
                    extra = [
                        p
                        for p in extra
                        if p.published_at
                        and (not publication_from or p.published_at[:10] >= publication_from)
                        and (not publication_to or p.published_at[:10] <= publication_to)
                    ]
                papers.extend(extra)
                warnings.extend(browser_result.get("warnings", []))
                warnings.append("API 来源不可用或限流，已使用本地 Chrome 补充搜索")
            except ValueError as exc:
                warnings.append(str(exc))
        return self.finish_search(
            papers,
            warnings,
            requested_limit,
            sort,
            year_from,
            year_to,
            browser_result,
            venues,
            publisher,
            include_claimed,
        )

    def finish_search(
        self,
        papers,
        warnings,
        limit,
        sort,
        year_from,
        year_to,
        browser_result,
        venues=None,
        publisher=None,
        include_claimed=False,
    ):
        for paper in papers:
            if paper.venue_status == "unknown" and paper.venue_claim:
                metadata = venue_metadata(claims=paper.venue_claim)
                paper.venue, paper.venue_status = metadata["venue"], metadata["venue_status"]
        papers = [
            p
            for p in papers
            if not p.year
            or ((not year_from or p.year >= year_from) and (not year_to or p.year <= year_to))
        ]
        papers = deduplicate(papers)
        if venues or publisher:
            papers = [p for p in papers if matches_venue(p, venues, publisher, include_claimed)]
            warnings.append(
                "会场/机构筛选仅覆盖本次候选；作者声明不等于正式收录，未识别来源不会猜测归类。"
            )
        if len(browser_result.get("search_pages", [])) > 1:
            google = [p for p in papers if "google_research" in p.source_ids]
            other = [p for p in papers if "google_research" not in p.source_ids]
            papers = [
                group[i]
                for i in range(max(len(google), len(other)))
                for group in (other, google)
                if i < len(group)
            ]
        if sort == "date":
            papers.sort(key=lambda p: p.published_at or str(p.year or ""), reverse=True)
        elif sort == "citations":
            papers.sort(key=lambda p: p.citation_count, reverse=True)
        papers = papers[:limit]
        for p in papers:
            self.store.put("paper", p.model_dump())
        return {
            "papers": [p.model_dump() for p in papers],
            "warnings": warnings + self.net.warnings,
            "search_pages": browser_result.get("search_pages", []),
            "transport": browser_result.get("transport", "api"),
            "venue_links": [
                {"venue": v, "url": PORTALS[v]}
                for v in [
                    *(canonical_venue(x) for x in venues or []),
                    *([publisher] if publisher else []),
                ]
                if v in PORTALS
            ],
        }

    async def resolve(self, seed):
        try:
            return Paper.model_validate(self.store.get(seed, "paper")), []
        except ValueError:
            pass
        if re.match(r"^(https://openalex.org/)?W\d+$", seed):
            return from_openalex(await self.oa("/" + seed.split("/")[-1])), []
        if (normalize_doi(seed) or "").startswith("10."):
            try:
                return from_openalex(
                    await self.oa("/" + quote("https://doi.org/" + normalize_doi(seed), safe=":"))
                ), []
            except ValueError as exc:
                self.net.warnings.append(str(exc))
                return from_semantic(
                    await self.s2(
                        "DOI:" + normalize_doi(seed),
                        {
                            "fields": "title,authors,year,abstract,url,externalIds,publicationDate,openAccessPdf,venue,publicationVenue"
                        },
                    )
                ), []
        if seed.startswith("S2:"):
            return from_semantic(
                await self.s2(
                    seed[3:],
                    {
                        "fields": "title,authors,year,abstract,url,externalIds,publicationDate,openAccessPdf,venue,publicationVenue"
                    },
                )
            ), []
        arxiv = re.sub(r"^(arxiv:|ARXIV:|https?://arxiv.org/abs/)", "", seed)
        if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", arxiv):
            return from_semantic(
                await self.s2(
                    "ARXIV:" + arxiv,
                    {
                        "fields": "title,authors,year,abstract,url,externalIds,publicationDate,openAccessPdf,venue,publicationVenue"
                    },
                )
            ), []
        candidates = (await self.search(seed, limit=5))["papers"]
        exact = [p for p in candidates if p["title"].casefold().strip() == seed.casefold().strip()]
        if len(exact) == 1:
            return Paper.model_validate(exact[0]), []
        return None, candidates

    async def download(self, paper_id):
        paper = Paper.model_validate(self.store.get(paper_id, "paper"))
        url = paper.pdf_url
        if not url and paper.arxiv_id:
            url = "https://arxiv.org/pdf/" + paper.arxiv_id
        if not url:
            raise ValueError("数据源没有提供开放 PDF 地址，请通过论文原文页查询获取方式")
        raw = await self.net.get(url, binary=True)
        if not raw.lstrip().startswith(b"%PDF-"):
            raise ValueError("该链接未返回 PDF，可能需要登录或已失效；请打开原文页")
        directory = Path(self.settings.data_dir) / "paper-downloads"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (hashlib.sha256(paper.id.encode()).hexdigest()[:24] + ".pdf")
        # Write atomically so concurrent download/read operations see a complete file.
        import os
        import tempfile

        fd, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {
            "paper": paper.model_dump(),
            "pdf_path": str(path),
            "source_url": url,
            "warnings": self.net.warnings,
        }

    async def related(self, seed: str, limit=50, offset=0, similar_limit=10, direction="both", **_):
        if not 1 <= limit <= 100 or offset < 0 or not 0 <= similar_limit <= 20:
            raise ValueError("limit 为 1–100，offset 非负，similar_limit 为 0–20")
        paper, candidates = await self.resolve(seed)
        if not paper:
            return {"status": "needs_selection", "candidates": candidates, "warnings": []}
        self.store.put("paper", paper.model_dump())
        nodes, edges, warnings, pagination = [paper], [], [], {}
        fields = "title,authors,year,abstract,url,externalIds,citationCount,publicationDate,openAccessPdf,venue,publicationVenue"
        sid = paper.source_ids.get("semantic") or (
            "DOI:" + paper.doi
            if paper.doi
            else "ARXIV:" + paper.arxiv_id
            if paper.arxiv_id
            else None
        )
        requested_direction = direction
        for direction in ("references", "citations") if direction == "both" else (direction,):
            found = []
            try:
                if sid:
                    body = await self.s2(
                        quote(sid, safe=":") + "/" + direction,
                        {"fields": fields, "limit": limit, "offset": offset},
                    )
                    key = "citedPaper" if direction == "references" else "citingPaper"
                    found = [
                        from_semantic(r[key])
                        for r in body.get("data", [])
                        if r.get(key) and r[key].get("paperId")
                    ]
                    pagination[direction] = {
                        "next_offset": body.get("next"),
                        "truncated": body.get("next") is not None,
                    }
                else:
                    raise ValueError("该论文缺少 Semantic Scholar 可解析标识")
            except ValueError as exc:
                warnings.append(str(exc))
                if "openalex" in paper.source_ids:
                    try:
                        oa_id = paper.source_ids["openalex"].split("/")[-1]
                        if direction == "references":
                            body = await self.oa("/" + oa_id)
                            refs = body.get("referenced_works", [])
                            for rid in refs[offset : offset + limit]:
                                found.append(from_openalex(await self.oa("/" + rid.split("/")[-1])))
                            total = len(refs)
                        else:
                            body = await self.oa(
                                params={
                                    "filter": "cites:" + oa_id,
                                    "per-page": limit,
                                    "page": offset // limit + 1,
                                }
                            )
                            entries = body["results"]
                            remainder = offset % limit
                            if remainder and (offset // limit + 1) * limit < body["meta"]["count"]:
                                following = await self.oa(
                                    params={
                                        "filter": "cites:" + oa_id,
                                        "per-page": limit,
                                        "page": offset // limit + 2,
                                    }
                                )
                                entries = entries + following["results"]
                            found = [
                                from_openalex(r) for r in entries[remainder : remainder + limit]
                            ]
                            total = body["meta"]["count"]
                        pagination[direction] = {
                            "next_offset": offset + limit if offset + limit < total else None,
                            "truncated": offset + limit < total,
                        }
                    except ValueError as fallback:
                        warnings.append(str(fallback))
            for p in found:
                nodes.append(p)
                edges.append(
                    PaperRelation(
                        source=paper.id if direction == "references" else p.id,
                        target=p.id if direction == "references" else paper.id,
                        kind="cites",
                    ).model_dump()
                )
        if similar_limit:
            search_result = await self.search(paper.title, limit=30)
            warnings.extend(search_result["warnings"])
            candidates = search_result["papers"]
            pool = [
                Paper.model_validate(p)
                for p in candidates
                if p["id"] != paper.id
                and not (p["doi"] and p["doi"] == paper.doi)
                and not (
                    p["arxiv_id"]
                    and paper.arxiv_id
                    and re.sub(r"v\d+$", "", p["arxiv_id"]) == re.sub(r"v\d+$", "", paper.arxiv_id)
                )
            ]
            try:
                import numpy as np

                vectors = np.array(
                    await asyncio.to_thread(
                        self.embedder.encode,
                        [paper.title + " " + paper.abstract]
                        + [p.title + " " + p.abstract for p in pool],
                    )
                )
                ranked = sorted(zip(pool, vectors[1:] @ vectors[0]), key=lambda x: -x[1])[
                    :similar_limit
                ]
                for p, score in ranked:
                    nodes.append(p)
                    edges.append(
                        PaperRelation(
                            source=paper.id, target=p.id, kind="similar", score=float(score)
                        ).model_dump()
                    )
            except (ValueError, OSError) as exc:
                warnings.append(str(exc))
        merged = deduplicate(nodes)
        aliases = {}
        for p in nodes:
            canonical = next(
                (
                    m
                    for m in merged
                    if m.id == p.id
                    or (p.doi and m.doi == p.doi)
                    or (
                        p.arxiv_id
                        and m.arxiv_id
                        and re.sub(r"v\d+$", "", m.arxiv_id) == re.sub(r"v\d+$", "", p.arxiv_id)
                    )
                ),
                p,
            )
            aliases[p.id] = canonical.id
        unique_edges = {}
        for e in edges:
            e["source"], e["target"] = aliases[e["source"]], aliases[e["target"]]
            if e["source"] != e["target"]:
                unique_edges[(e["source"], e["target"], e["kind"])] = e
        for p in merged:
            self.store.put("paper", p.model_dump())
        return {
            "seed": paper.model_dump(),
            "papers": [p.model_dump() for p in merged],
            "relations": list(unique_edges.values()),
            "pagination": pagination,
            "page_size": limit,
            "offset": offset,
            "direction": requested_direction,
            "warnings": warnings + self.net.warnings,
            "id": "graph-" + hashlib.sha256(seed.encode()).hexdigest()[:16],
        }
