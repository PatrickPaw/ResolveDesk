from app.api.access import require_admin
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.ollama_provider import OllamaProvider
from app.core.config import settings
from app.db.database import get_db
from app.db.resolved_incident_repository import (
    PostgreSQLResolvedIncidentRepository,
)
from app.models.resolved_incident import ResolvedIncident


router = APIRouter(
    dependencies=[Depends(require_admin)],
    prefix="/resolved-incidents",
    tags=["Resolved Incidents"],
)

ai_provider = OllamaProvider(
    model=settings.ollama_model,
    embedding_model=settings.ollama_embedding_model,
)


def build_embedding_text(
    incident: ResolvedIncident,
) -> str:
    parts = [
        f"Summary: {incident.summary}",
        f"Category: {incident.category.value}",
    ]

    if incident.subcategory is not None:
        parts.append(
            f"Subcategory: {incident.subcategory}"
        )

    if incident.error_message is not None:
        parts.append(
            f"Error: {incident.error_message}"
        )

    parts.append(
        f"Resolution: {incident.resolution}"
    )

    return "\n".join(parts)


@router.get(
    "",
    response_model=list[ResolvedIncident],
)
def list_resolved_incidents(
    verified: bool | None = None,
    db: Session = Depends(get_db),
):
    repository = PostgreSQLResolvedIncidentRepository(db)

    return repository.list(
        technician_verified=verified
    )


@router.get(
    "/{incident_id}",
    response_model=ResolvedIncident,
)
def get_resolved_incident(
    incident_id: str,
    db: Session = Depends(get_db),
):
    repository = PostgreSQLResolvedIncidentRepository(db)

    incident = repository.get(incident_id)

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resolved incident not found.",
        )

    return incident


@router.patch(
    "/{incident_id}/verify",
    response_model=ResolvedIncident,
)
def verify_resolved_incident(
    incident_id: str,
    db: Session = Depends(get_db),
):
    repository = PostgreSQLResolvedIncidentRepository(db)

    incident = repository.get(incident_id)

    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resolved incident not found.",
        )

    embedding_text = build_embedding_text(
        incident
    )

    embedding = ai_provider.embed_document(
        embedding_text
    )

    verified_incident = repository.set_verified(
        incident_id=incident_id,
        verified=True,
        embedding=embedding,
    )

    if verified_incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resolved incident not found.",
        )

    return verified_incident