from typing import Protocol

from app.models.conversation import DiagnosticState
from app.models.incident import IncidentState
from app.models.knowledge import KnowledgeArticle


class KnowledgeRepository(Protocol):
    def search(
        self,
        incident: IncidentState,
        limit: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[KnowledgeArticle]:
        ...


def build_knowledge_query_text(
    incident: IncidentState,
    diagnostic: DiagnosticState,
) -> str:
    parts = []

    if incident.summary is not None:
        parts.append(
            f"Problem: {incident.summary}"
        )

    if incident.category is not None:
        parts.append(
            f"Category: {incident.category.value}"
        )

    if incident.subcategory is not None:
        parts.append(
            f"Subcategory: {incident.subcategory}"
        )

    if incident.error_message is not None:
        parts.append(
            f"Incident error: {incident.error_message}"
        )

    if incident.technical_observations:
        parts.append("User-reported observations (unverified; newest first):")
        parts.extend(f"- {item}" for item in reversed(incident.technical_observations))

    if diagnostic.playbook_id is not None:
        parts.append(
            f"Diagnostic playbook: {diagnostic.playbook_id}"
        )

    for key, value in sorted(
        diagnostic.facts.items()
    ):
        if isinstance(value, bool):
            formatted_value = (
                "YES"
                if value
                else "NO"
            )
        else:
            formatted_value = str(value)

        parts.append(
            f"{key}: {formatted_value}"
        )

    return "\n".join(parts)


def retrieve_knowledge(
    repository: KnowledgeRepository,
    incident: IncidentState,
    query_embedding: list[float],
    limit: int = 5,
) -> list[KnowledgeArticle]:
    articles = repository.search(
        incident=incident,
        limit=limit,
        query_embedding=query_embedding,
    )

    return [
        article
        for article in articles
        if article.active
    ]
