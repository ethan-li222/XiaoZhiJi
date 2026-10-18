from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def new_id() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat()


class Paper(BaseModel):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    published_at: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    abstract: str = ""
    url: str = ""
    pdf_url: str | None = None
    citation_count: int = 0
    source_ids: dict[str, str] = Field(default_factory=dict)
    venue: str | None = None
    venue_status: Literal["indexed", "author_claim", "unknown"] = "unknown"
    venue_claim: str = ""
    publisher: str | None = None


class PaperRelation(BaseModel):
    source: str
    target: str
    kind: Literal["cites", "similar"]
    score: float | None = None


class DocumentChunk(BaseModel):
    id: str
    document_id: str
    text: str
    source: str
    title: str
    section: str = ""
    page: int | None = None
    paragraph: int = 0


class ReadingSession(BaseModel):
    id: str = Field(default_factory=new_id)
    document_id: str
    history: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeEntry(BaseModel):
    id: str = Field(default_factory=new_id)
    question: str
    answer: str
    selection: str = ""
    document_id: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now)
    status: Literal["inbox", "confirmed", "archived"] = "inbox"
    notes: str = ""
    session_id: str | None = None
    turn_index: int | None = None
    revision: int = 1
    updated_at: str = Field(default_factory=now)


class GroundedAnswer(BaseModel):
    answer: str
    evidence_ids: list[str] = Field(default_factory=list)


class Source(BaseModel):
    id: str
    title: str
    url: str
    text: str
    published_at: str | None = None
    fetched_at: str = Field(default_factory=now)


class ReportSection(BaseModel):
    title: str
    text: str
    source_ids: list[str] = Field(default_factory=list)


class ReportDraft(BaseModel):
    title: str
    sections: list[ReportSection]


class Report(ReportDraft):
    id: str
    kind: Literal["research", "industry"]
    topic: str
    sources: list[Source]
    unknown_date_sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now)


class ChartSeries(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    name: str
    labels: list[str]
    values: list[float]


class Slide(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    notes: str = ""
    source_ids: list[str] = Field(default_factory=list)
    table: list[list[str]] = Field(default_factory=list)
    chart: list[ChartSeries] = Field(default_factory=list)


class SlideDeck(BaseModel):
    title: str
    slides: list[Slide] = Field(min_length=1, max_length=50)
    sources: list[Source] = Field(default_factory=list)


ACTIONS = Literal[
    "papers.search",
    "chat.send",
    "papers.related",
    "papers.download",
    "papers.map",
    "documents.import",
    "documents.open",
    "memory.note.save",
    "memory.note.delete",
    "memory.search",
    "memory.review",
    "memory.export",
    "documents.delete",
    "reading.ask",
    "knowledge.save",
    "knowledge.search",
    "knowledge.delete",
    "knowledge.update",
    "knowledge.review",
    "knowledge.export",
    "reports.generate",
    "slides.outline",
    "slides.build",
    "slides.revise",
    "workspace.project.save",
    "workspace.library.add",
    "workspace.library.update",
    "workspace.library.acquire",
    "workspace.import",
    "workspace.annotation.save",
    "workspace.idea.save",
    "workspace.experiment.save",
    "workspace.reading.log",
    "workspace.stats",
    "workspace.synthesize",
    "workspace.weekly",
    "workspace.coach",
    "workspace.profile.save",
    "workspace.decision.save",
]


class TaskRequest(BaseModel):
    action: ACTIONS
    params: dict[str, Any] = Field(default_factory=dict)


class TaskResult(BaseModel):
    id: str
    action: str
    params: dict[str, Any]
    status: Literal["pending", "running", "completed", "failed", "interrupted"] = "pending"
    stage: str = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
