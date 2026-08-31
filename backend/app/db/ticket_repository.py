from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TicketRecord
from app.models.ticket import EscalationTicket, TicketStatus


class PostgreSQLTicketRepository:
    def __init__(self, db: Session):
        self.db = db

    def save(
        self,
        ticket: EscalationTicket,
    ) -> None:
        record = TicketRecord(
            ticket_id=ticket.ticket_id,
            conversation_id=ticket.conversation_id,
            incident_state=ticket.incident.model_dump(
                mode="json"
            ),
            diagnostic_state=ticket.diagnostic.model_dump(mode="json"),
            routing=ticket.routing.model_dump(mode="json"),
            resolution_attempts=[
                attempt.model_dump(mode="json")
                for attempt in ticket.resolution_attempts
            ],
            escalation_reason=ticket.escalation_reason,
            status=ticket.status.value,
            created_at=ticket.created_at,
        )

        self.db.add(record)
        self.db.flush()

    def get(
        self,
        ticket_id: str,
    ) -> EscalationTicket | None:
        record = self.db.get(
            TicketRecord,
            ticket_id,
        )

        if record is None:
            return None

        return self._to_ticket(record)

    def get_by_conversation_id(self, conversation_id: str) -> EscalationTicket | None:
        record = self.db.scalar(
            select(TicketRecord)
            .where(TicketRecord.conversation_id == conversation_id)
            .order_by(TicketRecord.created_at.desc())
            .limit(1)
        )
        return self._to_ticket(record) if record is not None else None

    def list(
        self,
        status: TicketStatus | None = None,
    ) -> list[EscalationTicket]:
        statement = select(
            TicketRecord
        )

        if status is not None:
            statement = statement.where(
                TicketRecord.status == status.value
            )

        statement = statement.order_by(
            TicketRecord.created_at.desc()
        )

        records = self.db.scalars(
            statement
        ).all()

        return [
            self._to_ticket(record)
            for record in records
        ]

    def update_status(
        self,
        ticket_id: str,
        status: TicketStatus,
    ) -> EscalationTicket | None:
        record = self.db.get(
            TicketRecord,
            ticket_id,
        )

        if record is None:
            return None

        record.status = status.value

        self.db.flush()
        self.db.refresh(record)

        return self._to_ticket(record)

    @staticmethod
    def _to_ticket(
        record: TicketRecord,
    ) -> EscalationTicket:
        return EscalationTicket.model_validate(
            {
                "ticket_id": record.ticket_id,
                "conversation_id": record.conversation_id,
                "incident": record.incident_state,
                "diagnostic": record.diagnostic_state,
                "routing": record.routing or {},
                "resolution_attempts": record.resolution_attempts,
                "escalation_reason": record.escalation_reason,
                "status": record.status,
                "created_at": record.created_at,
            }
        )
