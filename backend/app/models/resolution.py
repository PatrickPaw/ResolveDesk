from enum import Enum

from pydantic import BaseModel, Field


class ResolutionOutcome(str, Enum):
    CONTINUE = "CONTINUE"
    RESOLVED = "RESOLVED"
    ESCALATE = "ESCALATE"


class ResolutionStep(BaseModel):
    instruction: str = Field(min_length=1)
    source_id: str = Field(min_length=1)


class ResolutionProposal(BaseModel):
    applicable: bool
    step: ResolutionStep | None = None


class ResolutionFeedback(BaseModel):
    understood: bool
    clarification_requested: bool = False
    step_completed: bool | None = Field(default=None, description="True only for performing the current instruction; false only when unable/refusing. Null for unrelated observations or no active instruction.")
    problem_resolved: bool | None = Field(default=None, description="True: original fault on this user's device is explicitly fixed. False: user explicitly says the original fault still occurs. Null: result not stated, comparison on another device, or only step completion ('Zrobiłem to, co dalej?').")
    details: str | None = None


class ResolutionAttempt(BaseModel):
    step: ResolutionStep
    user_response: str | None = None
    step_completed: bool | None = None
    problem_resolved: bool | None = None


class ResolutionState(BaseModel):
    attempts: list[ResolutionAttempt] = Field(default_factory=list)
    outcome: ResolutionOutcome | None = None
    knowledge_exhausted: bool = False
    user_resolution: str | None = None
