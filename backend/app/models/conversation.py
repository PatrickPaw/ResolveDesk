from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.models.incident import IncidentAnalysis, IncidentState
from app.models.resolution import ResolutionFeedback, ResolutionState, ResolutionStep


DiagnosticValue = str | bool | int | float | None


class ConversationStage(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLUTION = "RESOLUTION"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"

    @classmethod
    def _missing_(cls, value):
                                                                 
        if value in {"TRIAGE", "DIAGNOSIS"}:
            return cls.ACTIVE
        return None


class MessageIntent(str, Enum):
    INCIDENT = "INCIDENT"
    SELF_SERVICE = "SELF_SERVICE"
    IT_EXPLANATION = "IT_EXPLANATION"
    SECURITY_INCIDENT = "SECURITY_INCIDENT"
    OFF_TOPIC = "OFF_TOPIC"


class MessageClassification(BaseModel):
    intent: MessageIntent
    security_emergency: bool = False
    sensitive_data_detected: bool = False


class MessageAnalysis(BaseModel):
    classification: MessageClassification
    incident: IncidentAnalysis = Field(description="Sparse incident patch; first reports include category, summary, issue_family and device/application subcategory.")
    feedback: ResolutionFeedback = Field(description="Interpret outcome at every stage, including self-resolution during business questions.")
    outcome_scope: Literal["ORIGINAL_PROBLEM", "STEP_ONLY", "OTHER_DEVICE", "UNSPECIFIED"] = Field(
        default="UNSPECIFIED", description="ORIGINAL_PROBLEM for explicit current success OR continued failure (e.g. nadal brak sygnału). STEP_ONLY for completing an instruction without saying whether it helped. OTHER_DEVICE for comparison results. UNSPECIFIED for no result.")
    resolution_evidence: str | None = Field(max_length=500, description="Required: exact quote from user_message proving their original fault is fixed, if feedback.problem_resolved=true; otherwise null.")
    incident_evidence: dict[str, str] = Field(
        default_factory=dict,
        max_length=16,
        description="Exact current-message quotes supporting extracted incident fields.",
    )

    def scoped_feedback(self) -> ResolutionFeedback:
        updates = {}
        if self.outcome_scope != "ORIGINAL_PROBLEM":
            updates["problem_resolved"] = None
        if self.outcome_scope in {"OTHER_DEVICE", "UNSPECIFIED"}:
            updates["step_completed"] = None
        return self.feedback.model_copy(update=updates)


class SecurityEventType(str, Enum):
    CREDENTIAL_EXPOSURE = "CREDENTIAL_EXPOSURE"
    PHISHING = "PHISHING"
    UNEXPECTED_MFA = "UNEXPECTED_MFA"
    SUSPICIOUS_LOGIN = "SUSPICIOUS_LOGIN"
    MALWARE = "MALWARE"
    LOST_DEVICE = "LOST_DEVICE"
    DATA_DISCLOSURE = "DATA_DISCLOSURE"
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"
    OTHER_SECURITY_EVENT = "OTHER_SECURITY_EVENT"


class SecurityAssessment(BaseModel):
    event_type: SecurityEventType | None = None
    evidence: str | None = None
    contains_secret: bool = False


class DiagnosticAnalysis(BaseModel):
    understood: bool
    facts: dict[str, DiagnosticValue] = Field(default_factory=dict, max_length=24)
    uncertain_facts: list[str] = Field(default_factory=list, max_length=8)
    evidence: dict[str, str] = Field(default_factory=dict, max_length=24,
        description="For every returned fact, an exact quote from the current user message supporting that fact. Never quote historical context.")


class FactEvidence(BaseModel):
    source_message_id: int | None = None
    status: Literal["reported", "suspected", "unknown"] = "reported"
    suspected_value: DiagnosticValue = None


class PendingQuestion(BaseModel):
    question_id: str
    fact_key: str | None = None
    target: Literal["incident", "diagnostic", "feedback"]
    answer_type: Literal["boolean", "text"] = "text"
    action_id: str | None = None


class DiagnosticSnapshot(BaseModel):
    catalog_version: str | None = None
    facts: dict[str, DiagnosticValue] = Field(default_factory=dict)
    fact_evidence: dict[str, FactEvidence] = Field(default_factory=dict)


class DiagnosticState(DiagnosticSnapshot):
    playbook_id: str | None = None
    pending_fact: str | None = None
    pending_question: PendingQuestion | None = None
    question_attempts: dict[str, int] = Field(default_factory=dict)
    contexts: dict[str, DiagnosticSnapshot] = Field(default_factory=dict)
    current_message_id: int | None = None


class ConversationState(BaseModel):
    conversation_id: str
    stage: ConversationStage = ConversationStage.ACTIVE
    incident: IncidentState = Field(default_factory=IncidentState)
    diagnostic: DiagnosticState = Field(default_factory=DiagnosticState)
    resolution: ResolutionState = Field(default_factory=ResolutionState)
    last_question: str | None = None
    security_emergency: bool = False


class MessageContext(BaseModel):
    stage: ConversationStage = ConversationStage.ACTIVE
    incident: IncidentState = Field(default_factory=IncidentState)
    diagnostic: DiagnosticState = Field(default_factory=DiagnosticState)
    last_question: str | None = None
    current_step: ResolutionStep | None = None
    resolution_goal: str | None = None

    @classmethod
    def from_conversation(cls, conversation: ConversationState) -> "MessageContext":
        current_step = None
        if conversation.stage == ConversationStage.RESOLUTION and conversation.resolution.attempts:
            current_step = conversation.resolution.attempts[-1].step
        return cls(
            stage=conversation.stage,
            incident=conversation.incident.model_copy(deep=True),
            diagnostic=conversation.diagnostic.model_copy(deep=True, update={"contexts": {}, "fact_evidence": {}}),
            last_question=conversation.last_question,
            current_step=current_step,
        )
