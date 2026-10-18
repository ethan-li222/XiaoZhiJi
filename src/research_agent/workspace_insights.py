from collections import Counter
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import Slide, SlideDeck, Source, now


class WorkspaceInsights:
    def __init__(self, workspace):
        self.workspace, self.store = workspace, workspace.store

    @staticmethod
    def window(days):
        end = datetime.now(ZoneInfo("Asia/Shanghai"))
        start = datetime.combine(end.date() - timedelta(days=days - 1), time.min, tzinfo=end.tzinfo)
        return start, end

    @staticmethod
    def within(value, start, end):
        if not value:
            return False
        try:
            date = datetime.fromisoformat(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            return start <= date <= end
        except ValueError:
            return False

    def materials(self, project_id):
        if project_id:
            self.workspace.project(project_id)
        return [
            x for x in self.store.list("library") if not project_id or x["project_id"] == project_id
        ]

    async def stats(self, project_id=None, days=7, **_):
        start, end = self.window(days)
        materials = self.materials(project_id)
        doc_ids = {x["document_id"] for x in materials if x.get("document_id")}
        events = [
            e
            for e in self.store.activities()
            if (not project_id or e.get("project_id") == project_id)
            and self.within(e["occurred_at"], start, end)
        ]
        records = {}
        for kind in ("annotation", "idea", "experiment", "reading_log", "decision"):
            records[kind] = [
                x
                for x in self.store.list(kind)
                if (not project_id or x["project_id"] == project_id)
                and self.within(x.get("created_at"), start, end)
            ]
        logs = records["reading_log"]
        records["annotation"].extend(
            {**n, "kind": "term" if "术语" in n["tags"] else "note"}
            for n in self.store.list("personal_note")
            if n.get("document_id") in doc_ids
            and n["status"] != "archived"
            and self.within(n["created_at"], start, end)
        )
        reading_days = {
            datetime.fromisoformat(x["created_at"]).astimezone(end.tzinfo).date().isoformat()
            for x in logs
        }
        qa_count, undated_qa = 0, 0
        for session in self.store.list("session"):
            if project_id and session["document_id"] not in doc_ids:
                continue
            for turn in session["history"]:
                if not turn.get("created_at"):
                    undated_qa += 1
                elif self.within(turn["created_at"], start, end):
                    qa_count += 1
        knowledge = [
            k
            for k in self.store.list("knowledge")
            if (not project_id or k["document_id"] in doc_ids)
            and k.get("status", "inbox") != "archived"
            and self.within(k.get("created_at"), start, end)
        ]
        completed = {
            e["record_id"]
            for e in events
            if e.get("verb") == "status_changed" and e.get("status") == "read"
        }
        note_kinds = Counter(x["kind"] for x in records["annotation"])
        linked_ideas = 0
        for idea in records["idea"]:
            try:
                if idea["source_ids"]:
                    for identifier in idea["source_ids"]:
                        self.workspace.source(identifier, idea["project_id"])
                    linked_ideas += 1
            except ValueError:
                pass
        metrics = {
            "materials_added": sum(self.within(m["created_at"], start, end) for m in materials),
            "reading_completions": len(completed),
            "reading_logs": len(logs),
            "self_reported_minutes": sum(x["minutes"] for x in logs),
            "recorded_reading_days": len(reading_days),
            "annotations": len(records["annotation"]),
            "knowledge_cards": len(knowledge),
            "reading_questions": qa_count,
            "ideas_created": len(records["idea"]),
            "ideas_with_valid_evidence": linked_ideas,
            "experiments_created": len(records["experiment"]),
            "experiments_completed": len(
                {
                    e["record_id"]
                    for e in events
                    if e.get("kind") == "experiment" and e.get("status") == "completed"
                }
            ),
            "industry_annotations": note_kinds["industry"],
            "term_annotations": note_kinds["term"],
        }
        warnings = [
            "阅读分钟数来自本人记录；标记已读和笔记数量不代表理解程度。",
            "尚无个人习惯的外部对照数据，不输出同龄人排名或能力分数。",
        ]
        if undated_qa:
            warnings.append(f"{undated_qa} 条历史问答没有时间戳，未计入本时间窗")
        eligible = days >= 14 and len(reading_days) >= 7 and len(logs) >= 7
        if not eligible:
            warnings.append(
                "习惯建议样本不足：建议先在至少 14 天窗口内记录 7 天阅读，再生成趋势建议。"
            )
        try:
            profile = self.store.get("workspace-profile", "profile")
        except ValueError:
            profile = {"goal": "研究产出与长期能力积累", "constraints": "", "stage": ""}
        return {
            "period": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "days": days,
                "timezone": "Asia/Shanghai",
            },
            "project_id": project_id,
            "metrics": metrics,
            "queue": dict(Counter(x["status"] for x in materials)),
            "note_types": dict(note_kinds),
            "recorded_dates": sorted(reading_days),
            "eligible_for_coaching": eligible,
            "profile": profile,
            "warnings": warnings,
        }

    async def sources(self, project_id, days):
        start, end = self.window(days)
        doc_projects = {}
        for item in self.materials(project_id):
            if item.get("document_id"):
                doc_projects.setdefault(item["document_id"], item["project_id"])
        candidates = [
            *self.store.list("annotation"),
            *self.store.list("knowledge"),
            *self.store.list("personal_note"),
        ]
        candidates.sort(key=lambda r: r.get("updated_at", r.get("created_at", "")), reverse=True)
        sources, warnings, budget = [], [], 30000
        for record in candidates:
            doc = record.get("document_id")
            if doc not in doc_projects or not self.within(
                record.get("updated_at", record.get("created_at")), start, end
            ):
                continue
            try:
                scope = record.get("project_id") or doc_projects[doc]
                if project_id and scope != project_id:
                    continue
                source = self.workspace.source(record["id"], scope)
            except ValueError as exc:
                warnings.append(str(exc))
                continue
            if budget <= 0 or len(sources) >= 40:
                warnings.append(
                    "本次综合只使用最近 40 条笔记、最多 30000 字的材料；缩小项目或时间窗可提高覆盖。"
                )
                break
            source["text"] = source["text"][: min(3000, budget)]
            budget -= len(source["text"])
            sources.append(source)
        return sources, warnings

    async def synthesize(self, project_id=None, days=7, question="", **_):
        sources, warnings = await self.sources(project_id, days)
        return {
            "sources": sources,
            "question": question,
            "project_id": project_id,
            "stats": await self.stats(project_id, days),
            "warnings": warnings,
        }

    async def coach(self, project_id=None, days=7, **_):
        return await self.stats(project_id, days)

    async def weekly(self, project_id=None, days=7, **_):
        stats = await self.stats(project_id, days)
        sources, warnings = await self.sources(project_id, days)
        project = (
            self.workspace.project(project_id)
            if project_id
            else {"name": "全部项目", "question": "", "next_step": ""}
        )
        start, end = self.window(days)
        ideas = [
            i
            for i in self.store.list("idea")
            if (not project_id or i["project_id"] == project_id)
            and self.within(i.get("updated_at"), start, end)
        ]
        experiments = [
            x
            for x in self.store.list("experiment")
            if (not project_id or x["project_id"] == project_id)
            and self.within(x.get("updated_at"), start, end)
        ]
        available = {s["id"] for s in sources}
        lines = [
            f"# {project['name']} · 最近 {days} 天工作汇报",
            "",
            f"时间：{stats['period']['start']} 至 {stats['period']['end']}",
            "",
            "## 研究目标",
            project.get("question") or "尚未填写研究问题",
            "",
            "## 已记录工作",
        ]
        labels = {
            "materials_added": "新增材料",
            "reading_completions": "标记已读",
            "self_reported_minutes": "自报阅读分钟",
            "annotations": "阅读批注",
            "knowledge_cards": "保存知识卡片",
            "ideas_created": "新增 Idea",
            "experiments_completed": "标记完成实验",
        }
        lines += [f"- {label}：{stats['metrics'][key]}" for key, label in labels.items()]
        lines += ["", "## 阅读与行业收获"]
        for source in sources:
            lines += [
                f"### {source['title']} [{source['id']}]",
                source["text"],
                "来源：" + source["url"],
                "",
            ]
        lines += ["## Idea 与实验（假设与实际结果分列）"]
        for idea in ideas:
            invalid = []
            for identifier in idea["source_ids"]:
                try:
                    self.workspace.source(identifier, idea["project_id"])
                except ValueError:
                    invalid.append(identifier)
            lines += [
                f"- {idea['title']}：{idea['hypothesis']}；阶段 {idea['status']}；新颖性 {idea['novelty_status']}",
                "  下一步：" + idea["next_step"],
            ]
            if invalid:
                warnings.append(idea["title"] + " 的部分证据已失效：" + ", ".join(invalid))
        for exp in experiments:
            lines += [
                f"- 实验 {exp['title']}：{exp['status']}",
                "  预期：" + exp["expected_result"],
                "  实际：" + (exp["actual_result"] or "未记录结果"),
            ]
        lines += [
            "",
            "## 下一步",
            project.get("next_step") or "请补充下阶段计划",
            "",
            "## 覆盖与限制",
            *stats["warnings"],
            *warnings,
        ]
        metric_id = "metrics:" + (project_id or "all") + ":" + str(days)
        metric_source = Source(
            id=metric_id,
            title="个人工作记录统计",
            url="",
            text="\n".join(f"{k}: {v}" for k, v in stats["metrics"].items()),
        ).model_dump()
        ppt_sources = [
            Source.model_validate(
                {k: v for k, v in s.items() if k in Source.model_fields}
            ).model_dump()
            for s in sources
        ]
        ppt_sources.append(metric_source)

        def slide(title, bullets, ids=None, notes=""):
            return Slide(
                title=title,
                bullets=bullets[:6] or ["本时间窗暂无记录"],
                source_ids=ids or [],
                notes=notes,
            )

        deck = SlideDeck(
            title=f"{project['name']} · 个人工作汇报",
            sources=ppt_sources,
            slides=[
                slide(
                    "研究问题与本期目标",
                    [
                        project.get("question") or "待补充研究问题",
                        stats["profile"]["goal"],
                        f"统计时间窗：最近 {days} 天",
                    ],
                ),
                slide(
                    "工作记录概览",
                    [f"{label}：{stats['metrics'][key]}" for key, label in labels.items()],
                    [metric_id],
                    notes="数值来自工作记录，不代表能力评分。",
                ),
                slide(
                    "论文与行业阅读收获",
                    [s["title"] + "：" + s["text"][:180] for s in sources[:6]],
                    [s["id"] for s in sources[:6]],
                    notes="\n\n".join(s["text"] for s in sources[:6]),
                ),
                slide(
                    "待验证 Idea",
                    [i["title"] + "：" + i["hypothesis"][:220] for i in ideas],
                    sorted({sid for i in ideas for sid in i["source_ids"] if sid in available}),
                    notes="Idea 为个人研究假设，新颖性须单独核验。",
                ),
                slide(
                    "实验方案与实际进展",
                    [
                        x["title"]
                        + "："
                        + x["status"]
                        + "；实际："
                        + (x["actual_result"][:180] or "尚未记录")
                        for x in experiments
                    ],
                ),
                slide(
                    "问题、下一步与覆盖限制",
                    [
                        project.get("next_step") or "请补充下一步",
                        *stats["warnings"][:3],
                        *warnings[:2],
                    ],
                ),
            ],
        )
        return {
            "project_id": project_id,
            "markdown": "\n".join(lines),
            "stats": stats,
            "deck": deck.model_dump(),
            "sources": sources,
            "warnings": warnings + stats["warnings"],
            "created_at": now(),
        }
