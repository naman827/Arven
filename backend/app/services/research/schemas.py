"""Structured-output schemas for the research workflow."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SubQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=400)
    evidence_needed: str = Field(default="", max_length=600)


class ResearchPlan(BaseModel):
    main_question: str = Field(max_length=800)
    deliverable_type: str = Field(default="research report", max_length=120)
    subquestions: list[SubQuestion] = Field(min_length=1, max_length=7)
    time_sensitive_claims: list[str] = Field(default_factory=list, max_length=10)
    stop_conditions: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("subquestions")
    @classmethod
    def _cap(cls, v: list[SubQuestion]) -> list[SubQuestion]:
        return v[:7]


class QuerySet(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=6)

    @field_validator("queries")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for q in v:
            q = q.strip().strip('"')[:300]
            if q and q.lower() not in (s.lower() for s in seen):
                seen.append(q)
        if not seen:
            raise ValueError("no usable queries")
        return seen


class Finding(BaseModel):
    statement: str = Field(max_length=800)
    citations: list[int] = Field(default_factory=list)


class SubQuestionAnalysis(BaseModel):
    findings: list[Finding] = Field(default_factory=list, max_length=12)
    coverage: float = Field(ge=0.0, le=1.0, description="0 = no evidence, 1 = fully answered by multiple independent sources")
    gaps: list[str] = Field(default_factory=list, max_length=5)
    conflicts: list[str] = Field(default_factory=list, max_length=5)
    follow_up_queries: list[str] = Field(default_factory=list, max_length=3)


class ClaimVerdict(BaseModel):
    id: int
    verdict: Literal["supported", "partial", "unsupported"]


class VerificationBatch(BaseModel):
    results: list[ClaimVerdict]
