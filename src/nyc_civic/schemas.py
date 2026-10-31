from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ScoreStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    DESCRIPTIVE = "descriptive"


NodeType = Literal["domain", "subcategory", "dimension", "indicator"]


class APIMessage(BaseModel):
    detail: str


class Geography(BaseModel):
    geo_id: str
    level: str
    name: str
    borough: str | None = None
    population: int | None = None
    is_residential: bool = True


class GeographyList(BaseModel):
    data_version: str
    items: list[Geography]


class ScoreNode(BaseModel):
    node_type: NodeType
    node_id: str
    name: str


class Legend(BaseModel):
    min: float = 0
    max: float = 100
    direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"
    is_relative: bool = False


class ScoreValue(BaseModel):
    geo_id: str
    score: float | None = Field(default=None, ge=0, le=100)
    coverage: float = Field(ge=0, le=1)
    status: ScoreStatus
    raw_value: float | None = None
    unit: str | None = None
    reason: str | None = None
    reference_period: str | None = None


class ScoresResponse(BaseModel):
    node: ScoreNode
    level: str
    legend: Legend
    data_version: str
    values: list[ScoreValue]


class Benchmark(BaseModel):
    kind: str
    value: float | None = None
    source_commitment_id: str | None = None


class ScoreTreeNode(BaseModel):
    node_type: NodeType
    node_id: str
    name: str
    score: float | None = None
    coverage: float = Field(ge=0, le=1)
    status: ScoreStatus
    weight: float = 1
    raw_value: float | None = None
    unit: str | None = None
    is_relative: bool = False
    reference_period: str | None = None
    benchmark: Benchmark | None = None
    children: list["ScoreTreeNode"] = Field(default_factory=list)


class ScoreTreeResponse(BaseModel):
    data_version: str
    geo_id: str
    root: ScoreTreeNode


class Measure(BaseModel):
    key: str
    label: str
    value: float | str | None
    unit: str | None = None
    moe: float | None = None
    year: str | None = None
    source_slug: str | None = None


class MeasureGroup(BaseModel):
    key: str
    label: str
    measures: list[Measure]


class MeasureGroupsResponse(BaseModel):
    data_version: str
    geo_id: str
    groups: list[MeasureGroup]


class CitywideValue(BaseModel):
    agg_method: Literal["district_mean", "population_weighted"]
    score: float | None = Field(default=None, ge=0, le=100)
    coverage: float = Field(ge=0, le=1)
    status: ScoreStatus


class CitywideResponse(BaseModel):
    node: ScoreNode
    data_version: str
    values: list[CitywideValue]


class UploadPresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int = Field(gt=0)


class UploadPresignResponse(BaseModel):
    key: str
    upload_url: str
    method: Literal["PUT"] = "PUT"
    expires_in_seconds: int = 600


class SubmissionCreate(BaseModel):
    photo_keys: list[str] = Field(default_factory=list, max_length=4)
    description: str = Field(min_length=3, max_length=4000)
    lat: float = Field(ge=40.4774, le=40.9176)
    lng: float = Field(ge=-74.2591, le=-73.7004)
    observed_at: datetime
    category_hint: str | None = None

    @field_validator("photo_keys")
    @classmethod
    def keys_are_local_upload_keys(cls, values: list[str]) -> list[str]:
        if any(not key.startswith("uploads/") or ".." in key for key in values):
            raise ValueError("photo_keys must be keys returned by /uploads/presign")
        return values


class SafetyFlags(BaseModel):
    identifiable_people: bool = False
    license_plate_visible: bool = False
    inappropriate: bool = False
    off_topic: bool = False


class SubmissionClassification(BaseModel):
    is_urban_issue: bool
    domain: str | None = None
    subcategory: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    observation_type: str | None = None
    summary: str = ""
    severity: int | None = Field(default=None, ge=1, le=5)
    confidence: float | None = Field(default=None, ge=0, le=1)
    safety_flags: SafetyFlags = Field(default_factory=SafetyFlags)
    related_policy_ids: list[str] = Field(default_factory=list, max_length=3)
    policy_note: str | None = None


class SubmissionResponse(BaseModel):
    id: str
    status: Literal["processing", "classified", "failed"]
    poll_url: str
    error: str | None = None
    classification: SubmissionClassification | None = None


class DistrictInsightDraft(BaseModel):
    """The model-authored portion of a district interpretation."""

    headline: str = Field(min_length=1, max_length=140)
    explanation: str = Field(min_length=1, max_length=900)
    priority_indicator_ids: list[str] = Field(default_factory=list, max_length=3)
    related_policy_ids: list[str] = Field(default_factory=list, max_length=3)


class DistrictEvidence(BaseModel):
    indicator_id: str
    name: str
    score: float | None = Field(default=None, ge=0, le=100)
    raw_value: float | None = None
    unit: str | None = None
    status: ScoreStatus
    coverage: float = Field(ge=0, le=1)


class DistrictInsight(BaseModel):
    """A cached, source-constrained interpretation read by the UI."""

    geo_id: str
    node_type: NodeType
    node_id: str
    data_version: str
    headline: str
    explanation: str
    priority_indicator_ids: list[str] = Field(default_factory=list)
    related_policy_ids: list[str] = Field(default_factory=list)
    evidence: list[DistrictEvidence]
    caveat: str
    generated_at: datetime


class Commitment(BaseModel):
    id: str
    document_id: str
    document_title: str
    statement_type: str
    summary: str
    excerpt: str
    section_ref: str | None = None
    page: int | None = None
    agencies: list[str] = Field(default_factory=list)
    target_value: float | None = None
    target_unit: str | None = None
    deadline: str | None = None
    review_status: Literal["needs_review", "approved", "rejected"] = "needs_review"
    tags: list[str] = Field(default_factory=list)


class CommitmentList(BaseModel):
    data_version: str
    items: list[Commitment]


class Dataset(BaseModel):
    slug: str
    name: str
    publisher: str
    url: str
    format: str
    access_method: str
    limitations: str


class DatasetList(BaseModel):
    data_version: str
    items: list[Dataset]


class ExtractedCommitment(BaseModel):
    statement_type: Literal[
        "formal_responsibility",
        "strategic_priority",
        "operational_commitment",
        "quantitative_target",
        "aspirational",
    ]
    summary: str = Field(min_length=1, max_length=500)
    excerpt: str = Field(min_length=1, max_length=3000)
    agencies: list[str] = Field(default_factory=list)
    target_value: float | None = None
    target_unit: str | None = None
    deadline: str | None = None
    target_population: str | None = None
    domain: str | None = None
    subcategory: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    taxonomy_gap: str | None = None


class ExtractedCommitments(BaseModel):
    commitments: list[ExtractedCommitment] = Field(default_factory=list)


class IndicatorDetails(BaseModel):
    id: str
    name: str
    definition: str
    formula: str
    direction: str
    unit: str
    normalization: dict[str, Any]
    datasets: list[Dataset]
    reference_period: str | None = None
    limitations: str
    commitments: list[Commitment] = Field(default_factory=list)
    run_id: str | None = None
    spec_version: str = "local-1"


class ReportsSummary(BaseModel):
    geo_id: str
    count: int = 0
    per_10000_residents: float | None = None
    bias_warning: bool = True
