from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.incident import Category


class ResolvedIncident(BaseModel):
    incident_id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    conversation_id: str

    category: Category

    subcategory: str | None = None

    summary: str

    error_message: str | None = None

    resolution: str

    technician_verified: bool = False

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )