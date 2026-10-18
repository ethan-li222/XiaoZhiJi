"""Bounded, evidence-backed co-citation and bibliographic-coupling maps."""

import asyncio
import hashlib
import math
import time
from collections import Counter
from itertools import combinations
from urllib.parse import quote

from .models import Paper
from .papers import from_openalex, from_semantic


def compare_neighborhoods(left, right):
    """Cosine overlap of observed sets. Missing neighborhoods contribute no evidence."""
    refs = sorted(left["references"] & right["references"])
    citers = sorted(left["citations"] & right["citations"])
    bc = len(refs) / max(1, math.sqrt(len(left["references"]) * len(right["references"])))
    cc = len(citers) / max(1, math.sqrt(len(left["citations"]) * len(right["citations"])))
    return {
        "score": (bc + cc) / 2,
        "coupling_score": bc,
        "co_citation_score": cc,
        "shared_reference_count": len(refs),
        "shared_citing_count": len(citers),
        "shared_reference_ids": refs[:20],
        "shared_citing_ids": citers[:20],
    }


class LiteratureMap:
    def __init__(self, papers, sample_size, candidate_limit):
        self.tools = papers
        self.sample_size = sample_size
        self.candidate_limit = candidate_limit
        self.provider = "semantic"
        self.records, self.raw, self.cache = {}, {}, {}
        self.warnings, self.calls = [], 0
        self.budget = min(50, papers.settings.source_requests_per_run)
        self.deadline = time.monotonic() + min(120, max(1, papers.settings.tool_timeout - 15))

    async def request(self, provider, suffix="", params=None):
        if self.calls >= self.budget:
            raise ValueError("相似图请求预算已用尽，未获取部分邻域")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("相似图采集时间已用尽，保留已获取的证据")
        self.calls += 1
        try:
            return await asyncio.wait_for(
                getattr(self.tools, provider)(suffix, params), timeout=min(20, remaining)
            )
        except TimeoutError:
            raise ValueError("引用数据源响应超时，未获取此邻域") from None

    def remember(self, body):
        paper = from_openalex(body) if self.provider == "openalex" else from_semantic(body)
        self.records[paper.id] = paper.model_dump()
        self.raw[paper.id] = body
        return paper.id

    async def origin(self, paper):
        # Prefer a single ID namespace throughout each map; never equate papers by fuzzy title.
        try:
            identifier = paper.source_ids.get("openalex")
            if identifier:
                body = await self.request("oa", "/" + identifier.split("/")[-1])
            elif paper.doi:
                body = await self.request(
                    "oa", "/" + quote("https://doi.org/" + paper.doi, safe=":")
                )
            else:
                found = await self.request("oa", params={"search": paper.title, "per-page": 5})
                exact = [
                    w
                    for w in found.get("results", [])
                    if (w.get("title") or "").strip().casefold() == paper.title.strip().casefold()
                ]
                if len(exact) != 1:
                    raise ValueError("OpenAlex 未唯一匹配论文")
                body = exact[0]
            self.provider = "openalex"
            return self.remember(body)
        except ValueError as exc:
            self.warnings.append(str(exc) + "；尝试 Semantic Scholar")
        sid = paper.source_ids.get("semantic") or (
            "DOI:" + paper.doi
            if paper.doi
            else "ARXIV:" + paper.arxiv_id
            if paper.arxiv_id
            else None
        )
        if not sid:
            raise ValueError("无法获取该论文的引用邻域；请提供 DOI、arXiv ID 或可解析论文 ID")
        self.provider = "semantic"
        body = await self.request("s2", quote(sid, safe=":"), {"fields": self.fields})
        return self.remember(body)

    fields = (
        "title,authors,year,abstract,url,externalIds,citationCount,publicationDate,openAccessPdf"
    )

    async def hydrate(self, identifiers):
        missing = sorted(set(identifiers) - self.records.keys())[:100]
        if not missing or self.provider != "openalex":
            return
        try:
            body = await self.request(
                "oa",
                params={
                    "filter": "openalex:" + "|".join(i.split("/")[-1] for i in missing),
                    "per-page": len(missing),
                },
            )
            for item in body.get("results", []):
                self.remember(item)
        except ValueError as exc:
            self.warnings.append(str(exc))

    async def neighbors(self, identifier, direction):
        key = (identifier, direction)
        if key in self.cache:
            return self.cache[key]
        result = {"ids": set(), "complete": False, "total": None, "error": None}
        try:
            if self.provider == "openalex":
                if identifier not in self.raw:
                    self.remember(await self.request("oa", "/" + identifier.split("/")[-1]))
                if direction == "references":
                    raw = self.raw[identifier]
                    if "referenced_works" not in raw:
                        raise ValueError("数据源未提供参考文献字段")
                    # OpenAlex gives all reference IDs even when metadata hydration is capped.
                    result.update(
                        ids=set(raw["referenced_works"]),
                        complete=True,
                        total=len(set(raw["referenced_works"])),
                    )
                else:
                    body = await self.request(
                        "oa",
                        params={
                            "filter": "cites:" + identifier.split("/")[-1],
                            "per-page": self.sample_size,
                            "sort": "cited_by_count:desc",
                        },
                    )
                    ids = {self.remember(w) for w in body.get("results", [])}
                    total = body.get("meta", {}).get("count")
                    result.update(
                        ids=ids, total=total, complete=total is not None and len(ids) >= total
                    )
            else:
                body = await self.request(
                    "s2",
                    identifier.removeprefix("S2:") + "/" + direction,
                    {"fields": self.fields, "limit": self.sample_size, "offset": 0},
                )
                field = "citedPaper" if direction == "references" else "citingPaper"
                rows = body.get("data", [])
                ids = {
                    self.remember(row[field])
                    for row in rows
                    if row.get(field) and row[field].get("paperId")
                }
                complete = body.get("next") is None and len(ids) == len(rows)
                result.update(ids=ids, total=len(ids) if complete else None, complete=complete)
        except ValueError as exc:
            result["error"] = str(exc)
            self.warnings.append(f"{identifier} / {direction}: {exc}")
        result["ids"].discard(identifier)
        self.cache[key] = result
        return result

    def paper(self, identifier):
        return (
            self.records.get(identifier)
            or Paper(
                id=identifier,
                title="元数据未获取 · " + identifier,
                url=identifier
                if self.provider == "openalex"
                else "https://www.semanticscholar.org/paper/" + identifier.removeprefix("S2:"),
            ).model_dump()
        )

    async def build(self, seed, limit=20):
        try:
            origin, candidates = await asyncio.wait_for(
                self.tools.resolve(seed), timeout=max(1, self.deadline - time.monotonic())
            )
        except TimeoutError:
            raise ValueError("起点论文解析超时，请改用已检索的论文 ID 或 DOI") from None
        if not origin:
            return {"status": "needs_selection", "candidates": candidates, "warnings": []}
        root = await self.origin(origin)
        first = {d: await self.neighbors(root, d) for d in ("references", "citations")}
        candidate_ids = set().union(*(v["ids"] for v in first.values()))
        votes = Counter()
        # Expand both motifs to discover papers with no direct citation to the origin.
        for initial, reverse in (("references", "citations"), ("citations", "references")):
            for identifier in sorted(first[initial]["ids"])[:3]:
                neighborhood = await self.neighbors(identifier, reverse)
                candidate_ids.update(neighborhood["ids"])
                votes.update(neighborhood["ids"])
        candidate_ids.discard(root)
        # Prioritize candidates for which two-hop evidence was actually observed.
        ordered = sorted(candidate_ids, key=lambda i: (-votes[i], i))
        chosen = ordered[: self.candidate_limit - 1]
        await self.hydrate(chosen)
        snapshots = {}
        for identifier in [root, *chosen]:
            snapshots[identifier] = {
                d: set((await self.neighbors(identifier, d))["ids"])
                for d in ("references", "citations")
            }
        # A citation observed from either endpoint is evidence for both endpoints.
        for (identifier, direction), neighborhood in self.cache.items():
            reverse = "citations" if direction == "references" else "references"
            for other in neighborhood["ids"]:
                if other in snapshots and identifier != other:
                    snapshots[other][reverse].add(identifier)
        edges = []
        for left, right in combinations(snapshots, 2):
            scores = compare_neighborhoods(snapshots[left], snapshots[right])
            if scores["score"] > 0:
                edges.append({"source": left, "target": right, "kind": "bibliometric", **scores})
        # Rank reachable papers by strongest similarity path; no text-based fallback edges.
        strength = {root: 1.0}
        for _ in snapshots:
            changed = False
            for edge in edges:
                for a, b in ((edge["source"], edge["target"]), (edge["target"], edge["source"])):
                    value = strength.get(a, 0) * edge["score"]
                    if value > strength.get(b, 0):
                        strength[b] = value
                        changed = True
            if not changed:
                break
        selected = [
            root,
            *sorted((i for i in strength if i != root), key=lambda i: (-strength[i], i))[
                : limit - 1
            ],
        ]
        selected_set = set(selected)
        edges = [e for e in edges if e["source"] in selected_set and e["target"] in selected_set]
        direct = [
            {"source": i, "target": j, "kind": "cites"}
            for i in selected
            for j in sorted(snapshots[i]["references"] & selected_set)
            if i != j
        ]
        groups = {}
        for key, direction in (("prior_works", "references"), ("derivative_works", "citations")):
            counts = Counter(
                j for i in selected for j in snapshots[i][direction] if j not in selected_set
            )
            groups[key] = [
                {
                    "id": j,
                    "support_count": n,
                    "graph_paper_ids": [i for i in selected if j in snapshots[i][direction]],
                }
                for j, n in sorted(counts.items(), key=lambda p: (-p[1], p[0]))[:10]
                if n >= 2
            ]
        await self.hydrate([g["id"] for rows in groups.values() for g in rows])
        for rows in groups.values():
            for row in rows:
                row["paper"] = self.paper(row["id"])
        evidence_ids = {
            i
            for e in edges
            for field in ("shared_reference_ids", "shared_citing_ids")
            for i in e[field]
        }
        await self.hydrate(sorted(evidence_ids)[:100])
        coverage = [
            {
                "id": i,
                **{
                    d: {k: v for k, v in self.cache[(i, d)].items() if k != "ids"}
                    | {"observed": len(snapshots[i][d])}
                    for d in ("references", "citations")
                },
            }
            for i in snapshots
        ]
        for paper in self.records.values():
            self.tools.store.put("paper", paper)
        warnings = list(dict.fromkeys(self.warnings + self.tools.net.warnings))
        warnings.append("此图基于有界邻域采样；缺失连线不代表无关联，分数不是全库相似度。")
        if not edges:
            warnings.append("样本中没有足够的共同引用证据；可增大候选数量或改用直接引用图。")
        return {
            "graph_type": "bibliometric",
            "seed": self.paper(root),
            "papers": [
                self.paper(i) | {"similarity_to_origin_path": strength[i]} for i in selected
            ],
            "relations": edges,
            "citation_relations": direct,
            **groups,
            "evidence_papers": {i: self.paper(i) for i in sorted(evidence_ids)},
            "coverage": {
                "provider": self.provider,
                "candidate_count": len(candidate_ids),
                "evaluated_count": len(snapshots),
                "shown_count": len(selected),
                "sample_size": self.sample_size,
                "discovery_pivots_per_direction": 3,
                "requests": self.calls,
                "request_budget": self.budget,
                "neighborhoods": coverage,
                "bounded_sample": True,
            },
            "method": {
                "name": "observed-neighborhood-cosine-v1",
                "formula": "0.5 * (|R(a) ∩ R(b)| / sqrt(|R(a)||R(b)|) + |C(a) ∩ C(b)| / sqrt(|C(a)||C(b)|))",
                "description": "R 为观测到的参考文献集合，C 为观测到的引用者集合；空集合分量计 0。不是 Connected Papers 的原始算法。",
            },
            "warnings": warnings,
            "id": "map-" + hashlib.sha256(root.encode()).hexdigest()[:16],
        }
