from typing import Literal

from pydantic import BaseModel, Field

from .chat import ChatParams
from .personal_memory import PERSONAL_PARAMS
from .workspace_models import WORKSPACE_PARAMS


class SearchParams(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=100)
    year_from: int | None = Field(default=None, ge=1000, le=3000)
    year_to: int | None = Field(default=None, ge=1000, le=3000)
    sort: Literal["relevance", "date", "citations"] = "relevance"
    mode: Literal["auto", "api", "browser", "arxiv_browser", "google_research_browser"] = "auto"
    venues: list[str] = Field(default_factory=list, max_length=10)
    publisher: str | None = None
    include_claimed: bool = False


class OpenPaperParams(BaseModel):
    paper_id: str = Field(min_length=1)


class RelatedParams(BaseModel):
    seed: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    similar_limit: int = Field(default=10, ge=0, le=20)
    direction: Literal["both", "references", "citations"] = "both"


class DownloadParams(BaseModel):
    paper_id: str = Field(min_length=1)


class MapParams(BaseModel):
    seed: str = Field(min_length=1)
    limit: int = Field(default=20, ge=2, le=40)
    candidate_limit: int = Field(default=24, ge=3, le=40)
    sample_size: int = Field(default=50, ge=5, le=100)


class ImportParams(BaseModel):
    source: str = Field(min_length=1)
    text: str | None = None
    title: str | None = None


class DeleteParams(BaseModel):
    id: str = Field(min_length=1)


class AskParams(BaseModel):
    document_id: str
    question: str = Field(min_length=1)
    session_id: str | None = None
    selection: str = ""
    page: int | None = Field(default=None, ge=1)


class SaveParams(BaseModel):
    session_id: str
    turn: int = -1
    tags: list[str] = Field(default_factory=list)


class KnowledgeSearchParams(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=6, ge=1, le=30)
    status: Literal["inbox", "confirmed", "archived"] | None = None
    tag: str | None = None
    document_id: str | None = None


class KnowledgeUpdateParams(BaseModel):
    id: str
    revision: int = Field(ge=1)
    notes: str = Field(max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    status: Literal["inbox", "confirmed", "archived"]


class ReviewParams(BaseModel):
    days: int = Field(default=7, ge=1, le=3660)


class EmptyParams(BaseModel):
    pass


class ReportParams(BaseModel):
    topic: str = Field(min_length=1)
    kind: Literal["research", "industry"] = "research"
    days: int = Field(default=7, ge=1, le=366)
    sources: list[dict] = Field(default_factory=list)
    limit: int = Field(default=30, ge=1, le=100)


class OutlineParams(BaseModel):
    source: str = Field(min_length=1)
    pages: int = Field(default=10, ge=1, le=30)


class BuildParams(BaseModel):
    deck: dict


class ReviseParams(BaseModel):
    deck: dict
    page: int = Field(ge=1)
    instruction: str = Field(min_length=1)


PARAMS = {
    "chat.send": ChatParams,
    "papers.search": SearchParams,
    "papers.related": RelatedParams,
    "papers.download": DownloadParams,
    "papers.map": MapParams,
    "documents.import": ImportParams,
    "documents.open": OpenPaperParams,
    "documents.delete": DeleteParams,
    "reading.ask": AskParams,
    "knowledge.save": SaveParams,
    "knowledge.search": KnowledgeSearchParams,
    "knowledge.delete": DeleteParams,
    "knowledge.update": KnowledgeUpdateParams,
    "knowledge.review": ReviewParams,
    "knowledge.export": EmptyParams,
    "reports.generate": ReportParams,
    "slides.outline": OutlineParams,
    "slides.build": BuildParams,
    "slides.revise": ReviseParams,
}
PARAMS.update(WORKSPACE_PARAMS)
PARAMS.update(PERSONAL_PARAMS)


def validate_params(action, params):
    result = PARAMS[action].model_validate(params).model_dump(mode="json")
    if action == "papers.map" and result["limit"] > result["candidate_limit"]:
        raise ValueError("展示数量不能超过评估候选数量")
    for name in ("query", "topic", "question", "seed", "instruction", "source"):
        if name == "question" and action == "workspace.project.save":
            continue
        if name in result and isinstance(result[name], str) and not result[name].strip():
            raise ValueError(f"{name} 不能为空白")
    if (
        action == "papers.search"
        and result["year_from"]
        and result["year_to"]
        and result["year_from"] > result["year_to"]
    ):
        raise ValueError("起始年份不能晚于结束年份")
    if action == "slides.revise" and result["page"] > len(result["deck"].get("slides", [])):
        raise ValueError("修改页码超出大纲范围")
    return result
