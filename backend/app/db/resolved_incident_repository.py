from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ResolvedIncidentRecord
from app.models.resolved_incident import ResolvedIncident


class PostgreSQLResolvedIncidentRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(
        self,
        incident: ResolvedIncident,
        embedding: list[float] | None = None,
    ) -> None:
        existing = self.db.scalar(
            select(ResolvedIncidentRecord).where(
                ResolvedIncidentRecord.incident_id
                == incident.incident_id
            )
        )

        if existing is not None:
            raise ValueError(
                "Resolved incident already exists."
            )

        record = ResolvedIncidentRecord(
            incident_id=incident.incident_id,
            conversation_id=incident.conversation_id,
            category=incident.category.value,
            subcategory=incident.subcategory,
            summary=incident.summary,
            error_message=incident.error_message,
            resolution=incident.resolution,
            technician_verified=incident.technician_verified,
            embedding=embedding,
            created_at=incident.created_at,
        )

        self.db.add(record)
        self.db.flush()

    def get(
        self,
        incident_id: str,
    ) -> ResolvedIncident | None:
        record = self.db.scalar(
            select(ResolvedIncidentRecord).where(
                ResolvedIncidentRecord.incident_id
                == incident_id
            )
        )

        if record is None:
            return None

        return self._to_incident(record)

    def list(
        self,
        technician_verified: bool | None = None,
    ) -> list[ResolvedIncident]:
        statement = select(
            ResolvedIncidentRecord
        )

        if technician_verified is not None:
            statement = statement.where(
                ResolvedIncidentRecord.technician_verified
                == technician_verified
            )

        statement = statement.order_by(
            ResolvedIncidentRecord.created_at.desc()
        )

        records = self.db.scalars(
            statement
        ).all()

        return [
            self._to_incident(record)
            for record in records
        ]

    def set_verified(
        self,
        incident_id: str,
        verified: bool,
        embedding: list[float] | None = None,
    ) -> ResolvedIncident | None:
        record = self.db.scalar(
            select(ResolvedIncidentRecord).where(
                ResolvedIncidentRecord.incident_id
                == incident_id
            )
        )

        if record is None:
            return None

        record.technician_verified = verified

        if embedding is not None:
            record.embedding = embedding

        self.db.flush()
        self.db.refresh(record)

        return self._to_incident(record)

    @staticmethod
    def _to_incident(
        record: ResolvedIncidentRecord,
    ) -> ResolvedIncident:
        return ResolvedIncident.model_validate(
            {
                "incident_id": record.incident_id,
                "conversation_id": record.conversation_id,
                "category": record.category,
                "subcategory": record.subcategory,
                "summary": record.summary,
                "error_message": record.error_message,
                "resolution": record.resolution,
                "technician_verified": (
                    record.technician_verified
                ),
                "created_at": record.created_at,
            }
        )