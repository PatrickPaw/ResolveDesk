from typing import Literal

from pydantic import BaseModel, Field

from app.models.conversation import DiagnosticValue


class ExtractedFactTrace(BaseModel):
    key: str
    value: DiagnosticValue | list[str]
    source: Literal["AI", "LITERAL", "PYTHON"]
    evidence: str | None = None
    evidence_valid: bool = False


class ValidationTrace(BaseModel):
    check: str
    passed: bool
    detail: str


class DecisionTrace(BaseModel):
    decision_type: str
    source: Literal["PYTHON_RULE", "RAG", "SECURITY_RULE"]
    reason: str
    question_id: str | None = None
    action_source_id: str | None = None


class KnowledgeCandidateTrace(BaseModel):
    article_id: str
    title: str
    retrieval_method: Literal["VECTOR", "CATEGORY"]
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    selected: bool = False


class ExplainabilityTrace(BaseModel):
    mode: Literal["DEMO_ADMIN_ONLY"] = "DEMO_ADMIN_ONLY"
    input_text: str
    input_redacted: bool = False
    interpretation_source: Literal["AI", "LITERAL", "SECURITY_RULE"] | None = None
    intent: str | None = None
    incident_patch: dict = Field(default_factory=dict)
    extracted_facts: list[ExtractedFactTrace] = Field(default_factory=list)
    validations: list[ValidationTrace] = Field(default_factory=list)
    playbook_id: str | None = None
    playbook_version: str | None = None
    decisions: list[DecisionTrace] = Field(default_factory=list)
    knowledge_candidates: list[KnowledgeCandidateTrace] = Field(default_factory=list)
    escalation_reason: str | None = None
