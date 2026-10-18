from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .models import new_id, now


class Record(BaseModel):
    id: str = Field(default_factory=new_id)
    revision: int = 1
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)


class Project(Record):
    name: str
    question: str = ""
    keywords: list[str] = []
    venues: list[str] = []
    next_step: str = ""
    status: Literal["active", "paused", "completed"] = "active"


class LibraryItem(Record):
    project_id: str
    kind: Literal["paper", "industry"]
    title: str
    paper_id: str | None = None
    document_id: str | None = None
    source_url: str = ""
    venue: str = ""
    year: int | None = None
    tags: list[str] = []
    status: Literal["queued", "reading", "read", "archived"] = "queued"
    pdf_path: str | None = None
    organization: str = ""
    source_status: Literal["unverified", "official_domain", "user_confirmed"] = "unverified"
    published_at: str | None = None
    completed_at: str | None = None


class Annotation(Record):
    project_id: str
    document_id: str
    kind: Literal[
        "highlight", "question", "term", "method", "finding", "limitation", "industry", "note"
    ]
    selection: str = ""
    page: int | None = None
    text: str
    evidence_ids: list[str] = []
    tags: list[str] = []
    resolved: bool = False


class Idea(Record):
    project_id: str
    title: str
    problem: str = ""
    hypothesis: str
    difference: str = ""
    source_ids: list[str] = []
    risks: str = ""
    next_step: str = ""
    status: Literal[
        "draft", "needs_evidence", "ready", "testing", "supported", "rejected", "paused"
    ] = "draft"
    novelty_status: Literal["unchecked", "user_reviewed"] = "unchecked"


class Experiment(Record):
    project_id: str
    idea_id: str
    title: str
    baseline: str
    dataset: str
    metrics: str
    controls: str = ""
    ablations: str = ""
    budget: str = ""
    stopping_rule: str = ""
    expected_result: str = ""
    actual_result: str = ""
    status: Literal["designed", "running", "completed", "failed", "paused"] = "designed"


class WorkspaceParams(BaseModel):
    operation_id: str | None = None


class WriteParams(WorkspaceParams):
    id: str | None = None
    revision: int | None = Field(default=None, ge=1)


class ProjectParams(WriteParams):
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(default="", max_length=5000)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    venues: list[str] = Field(default_factory=list, max_length=30)
    next_step: str = Field(default="", max_length=3000)
    status: Literal["active", "paused", "completed"] = "active"


class LibraryAddParams(WorkspaceParams):
    project_id: str
    paper_id: str | None = None
    document_id: str | None = None
    kind: Literal["paper", "industry"] = "paper"
    tags: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def source_required(self):
        if not self.paper_id and not self.document_id:
            raise ValueError("需要提供论文或文档 ID")
        return self


class LibraryUpdateParams(WorkspaceParams):
    id: str
    revision: int = Field(ge=1)
    status: Literal["queued", "reading", "read", "archived"]
    tags: list[str] = Field(default_factory=list, max_length=30)
    venue: str = Field(default="", max_length=200)
    organization: str = Field(default="", max_length=200)
    source_status: Literal["unverified", "official_domain", "user_confirmed"] = "unverified"


class AcquireParams(WorkspaceParams):
    id: str


class WorkspaceImportParams(WorkspaceParams):
    project_id: str
    source: str = Field(min_length=1)
    title: str | None = None
    text: str | None = None
    kind: Literal["paper", "industry"] = "industry"
    organization: str = Field(default="", max_length=200)
    published_at: str | None = None


class AnnotationParams(WriteParams):
    project_id: str
    document_id: str
    kind: Literal[
        "highlight", "question", "term", "method", "finding", "limitation", "industry", "note"
    ] = "note"
    selection: str = Field(default="", max_length=12000)
    page: int | None = Field(default=None, ge=1)
    text: str = Field(min_length=1, max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    resolved: bool = False


class IdeaParams(WriteParams):
    project_id: str
    title: str = Field(min_length=1, max_length=300)
    problem: str = Field(default="", max_length=6000)
    hypothesis: str = Field(min_length=1, max_length=6000)
    difference: str = Field(default="", max_length=6000)
    source_ids: list[str] = Field(default_factory=list, max_length=40)
    risks: str = Field(default="", max_length=6000)
    next_step: str = Field(default="", max_length=6000)
    status: Literal[
        "draft", "needs_evidence", "ready", "testing", "supported", "rejected", "paused"
    ] = "draft"
    novelty_status: Literal["unchecked", "user_reviewed"] = "unchecked"


class ExperimentParams(WriteParams):
    idea_id: str
    title: str = Field(min_length=1, max_length=300)
    baseline: str = Field(min_length=1, max_length=6000)
    dataset: str = Field(min_length=1, max_length=6000)
    metrics: str = Field(min_length=1, max_length=6000)
    controls: str = Field(default="", max_length=6000)
    ablations: str = Field(default="", max_length=6000)
    budget: str = Field(default="", max_length=3000)
    stopping_rule: str = Field(default="", max_length=3000)
    expected_result: str = Field(default="", max_length=6000)
    actual_result: str = Field(default="", max_length=6000)
    status: Literal["designed", "running", "completed", "failed", "paused"] = "designed"


class ReadingLogParams(WorkspaceParams):
    id: str
    minutes: int = Field(ge=1, le=600)
    reflection: str = Field(default="", max_length=3000)


class WindowParams(WorkspaceParams):
    project_id: str | None = None
    days: int = Field(default=7, ge=1, le=366)


class SynthesisParams(WindowParams):
    question: str = Field(
        default="总结当前研究进展、证据差异、局限与可检验的研究假设", max_length=3000
    )


class ProfileParams(WorkspaceParams):
    goal: str = Field(default="研究产出与长期能力积累", max_length=3000)
    stage: str = Field(default="", max_length=1000)
    constraints: str = Field(default="", max_length=3000)
    weekly_hours: int | None = Field(default=None, ge=1, le=100)


class DecisionParams(WriteParams):
    project_id: str
    question: str = Field(min_length=1, max_length=3000)
    options: str = Field(min_length=1, max_length=6000)
    criteria: str = Field(default="", max_length=6000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    chosen: str = Field(default="", max_length=3000)
    review_date: str | None = None


class Finding(BaseModel):
    text: str
    source_ids: list[str] = Field(min_length=1)


class CandidateIdea(BaseModel):
    title: str
    hypothesis: str
    difference: str
    source_ids: list[str] = Field(min_length=1)
    validation: str
    uncertainty: str


class ResearchSynthesis(BaseModel):
    overview: str
    findings: list[Finding] = []
    disagreements: list[Finding] = []
    candidate_ideas: list[CandidateIdea] = []
    questions: list[str] = []


class HabitObservation(BaseModel):
    interpretation: str
    metric_keys: list[str] = Field(min_length=1)


class HabitOption(BaseModel):
    action: str
    benefit: str
    cost: str
    uncertainty: str
    metric_keys: list[str] = Field(min_length=1)


class HabitAdvice(BaseModel):
    observations: list[HabitObservation] = []
    options: list[HabitOption] = []
    trial_plan: str
    followup_questions: list[str] = []


WORKSPACE_PARAMS = {
    "workspace.project.save": ProjectParams,
    "workspace.library.add": LibraryAddParams,
    "workspace.library.update": LibraryUpdateParams,
    "workspace.library.acquire": AcquireParams,
    "workspace.import": WorkspaceImportParams,
    "workspace.annotation.save": AnnotationParams,
    "workspace.idea.save": IdeaParams,
    "workspace.experiment.save": ExperimentParams,
    "workspace.reading.log": ReadingLogParams,
    "workspace.stats": WindowParams,
    "workspace.synthesize": SynthesisParams,
    "workspace.weekly": WindowParams,
    "workspace.coach": WindowParams,
    "workspace.profile.save": ProfileParams,
    "workspace.decision.save": DecisionParams,
}
