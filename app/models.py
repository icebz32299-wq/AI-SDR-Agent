from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class SQLLead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_name: str = ""
    industry: str = ""
    area: str = ""
    contact_name: str = ""
    contact_title: str = ""
    phone: str = ""
    intent_level: Literal["high", "medium", "low"] = "low"
    intent_reason: str = ""
    demand_summary: str = ""
    mendian: str = ""
    shejishi: str = ""
    call_time: str = ""
    next_action: str = ""
    confidence_score: float = Field(default=0, ge=0, le=1)
    need_human_review: bool = True


EXTRACT_FIELDS = [
    "company_name",
    "industry",
    "area",
    "contact_name",
    "contact_title",
    "phone",
    "demand_summary",
    "mendian",
    "shejishi",
]


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(default="", max_length=1500)
    quote: str = Field(default="", max_length=2500)
    turn_id: str = ""


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strength: Literal[0, 1, 2] = 0
    quote: str = ""
    turn_id: str = ""
    explanation: str = ""


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, Fact] = Field(default_factory=dict)
    signals: dict[str, Signal] = Field(default_factory=dict)
    refusal: Fact = Field(default_factory=Fact)
    uncertainty: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=2, max_length=50000)
    title: str = Field(default="新通话", min_length=1, max_length=120)
    call_time: str = Field(default="", max_length=50)
    source: Literal[
        "manual", "assignment_example", "synthetic", "recording", "file"
    ] = "manual"
    upload_id: str | None = Field(default=None, max_length=64)
    recording_id: str | None = None
    mode: Literal["llm", "baseline"] = "llm"
    request_id: str = Field(default="", max_length=100)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=60)
    note: str = Field(min_length=2, max_length=1000)
    changes: dict[str, str] = Field(default_factory=dict)
    decision: Literal["approve", "reject"] = "approve"
    learn_alias: bool = False
    verification_source: str = Field(default="", max_length=1000)


class BatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    changes: dict[str, str] = Field(default_factory=dict)
    learn_alias: bool = False
    verification_source: str = Field(default="", max_length=1000)


class BatchReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[BatchItem] = Field(min_length=1, max_length=100)
    reviewer: str = Field(min_length=1, max_length=60)
    note: str = Field(min_length=2, max_length=1000)
    changes: dict[str, str] = Field(default_factory=dict)
    decision: Literal["approve", "reject"] = "approve"
