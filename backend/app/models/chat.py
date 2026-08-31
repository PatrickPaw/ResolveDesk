from pydantic import BaseModel, Field, field_validator
from uuid import UUID

from app.models.conversation import ConversationStage
from app.models.explainability import ExplainabilityTrace
from app.models.incident import IncidentState


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    conversation_id: str | None = None
    request_id: UUID | None = None
    include_explainability: bool = False

    @field_validator("message")
    @classmethod
    def require_nonblank_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be blank.")
        return value


class ChatResponse(BaseModel):
    conversation_id: str
    stage: ConversationStage
    incident: IncidentState
    reply: str
    ticket_id: str | None = None
    password_reset_demo_available: bool = False
    explainability: ExplainabilityTrace | None = None
