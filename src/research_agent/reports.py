import calendar
import hashlib
import re
from datetime import UTC, datetime, timedelta

import feedparser

from .models import Source


def filter_sources(sources, days, query, clock=None):
    clock = clock or datetime.now(UTC)
    cutoff = clock - timedelta(days=days)
    kept, unknown, seen = [], [], set()
    words = [w.casefold() for w in re.split(r"\s+", query) if w]
    for source in sources:
        canonical = source.url.rstrip("/")
        if canonical in seen:
            continue
        seen.add(canonical)
        if words and not any(w in (source.title + " " + source.text).casefold() for w in words):
            continue
        if not source.published_at:
            unknown.append(source)
            continue
        try:
            date = datetime.fromisoformat(source.published_at.replace("Z", "+00:00"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
        except ValueError:
            unknown.append(source)
            continue
        if cutoff <= date <= clock:
            kept.append(source)
    kept.sort(key=lambda x: x.published_at, reverse=True)
    return kept, unknown


class ReportTools:
    def __init__(self, papers, network):
        self.papers, self.net = papers, network

    async def collect(self, topic, kind="research", days=7, sources=None, limit=30, **_):
        if kind not in {"research", "industry"} or not 1 <= days <= 366 or not 1 <= limit <= 100:
            raise ValueError("kind 为 research/industry，days 为 1–366，limit 为 1–100")
        warnings, collected = [], []
        if kind == "research":
            now = datetime.now(UTC)
            result = await self.papers.search(
                topic,
                limit=limit,
                sort="date",
                publication_from=(now - timedelta(days=days)).date().isoformat(),
                publication_to=now.date().isoformat(),
            )
            warnings.extend(result["warnings"])
            for p in result["papers"]:
                collected.append(
                    Source(
                        id=p["id"],
                        title=p["title"],
                        url=p["url"],
                        text=p["abstract"] or p["title"],
                        published_at=p["published_at"],
                    )
                )
        for spec in sources or []:
            try:
                if spec.get("type", "rss") == "github":
                    repo = spec["repo"]
                    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                        raise ValueError("GitHub repo 应为 owner/repository")
                    releases = await self.net.get(
                        f"https://api.github.com/repos/{repo}/releases",
                        {"per_page": min(limit, 100)},
                    )
                    for r in releases:
                        if r.get("draft"):
                            continue
                        collected.append(
                            Source(
                                id="release-" + str(r["id"]),
                                title=r.get("name") or r["tag_name"],
                                url=r["html_url"],
                                text=(r.get("body") or "")[:12000],
                                published_at=r.get("published_at"),
                            )
                        )
                elif spec.get("type", "rss") == "rss":
                    xml = await self.net.get(spec["url"], json_response=False)
                    feed = feedparser.parse(xml)
                    if feed.bozo and not feed.entries:
                        raise ValueError("RSS/Atom 格式无效")
                    for e in feed.entries[:limit]:
                        url = e.get("link", "")
                        if not url:
                            continue
                        parsed = e.get("published_parsed") or e.get("updated_parsed")
                        date = (
                            datetime.fromtimestamp(calendar.timegm(parsed), UTC).isoformat()
                            if parsed
                            else None
                        )
                        from bs4 import BeautifulSoup

                        text = BeautifulSoup(e.get("summary", ""), "html.parser").get_text(
                            " ", strip=True
                        )
                        collected.append(
                            Source(
                                id="feed-" + hashlib.sha256(url.encode()).hexdigest()[:20],
                                title=e.get("title", url),
                                url=url,
                                text=text[:12000],
                                published_at=date,
                            )
                        )
                else:
                    raise ValueError("来源 type 只支持 rss 或 github")
            except (ValueError, KeyError) as exc:
                warnings.append(f"来源 {spec.get('repo') or spec.get('url', '未配置')}：{exc}")
        if kind == "industry" and not sources:
            raise ValueError("工业报告需要至少一个 RSS 或 GitHub Releases 来源")
        kept, unknown = filter_sources(collected, days, topic)
        return {
            "sources": [s.model_dump() for s in kept[:limit]],
            "unknown_date_sources": [s.model_dump() for s in unknown[:limit]],
            "warnings": warnings + self.net.warnings,
        }
