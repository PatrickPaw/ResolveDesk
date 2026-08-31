from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.incident import IncidentState
from app.models.conversation import DiagnosticState
from app.models.resolution import ResolutionAttempt
from app.models.routing import TicketRouting


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class EscalationTicket(BaseModel):
    ticket_id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    conversation_id: str
    incident: IncidentState
    diagnostic: DiagnosticState = Field(default_factory=DiagnosticState)

    resolution_attempts: list[ResolutionAttempt] = Field(
        default_factory=list
    )

    escalation_reason: str
    routing: TicketRouting = Field(default_factory=TicketRouting)

    status: TicketStatus = TicketStatus.OPEN

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
