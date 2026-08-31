from app.api.access import require_admin
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.ticket_repository import PostgreSQLTicketRepository
from app.models.ticket import EscalationTicket, TicketStatus


router = APIRouter(
    dependencies=[Depends(require_admin)],
    prefix="/tickets",
    tags=["Tickets"],
)


class TicketStatusUpdate(BaseModel):
    status: TicketStatus


@router.get(
    "",
    response_model=list[EscalationTicket],
)
def list_tickets(
    ticket_status: TicketStatus | None = None,
    db: Session = Depends(get_db),
):
    repository = PostgreSQLTicketRepository(db)

    return repository.list(
        status=ticket_status
    )


@router.get(
    "/{ticket_id}",
    response_model=EscalationTicket,
)
def get_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    repository = PostgreSQLTicketRepository(db)

    ticket = repository.get(ticket_id)

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    return ticket


@router.patch(
    "/{ticket_id}/status",
    response_model=EscalationTicket,
)
def update_ticket_status(
    ticket_id: str,
    data: TicketStatusUpdate,
    db: Session = Depends(get_db),
):
    repository = PostgreSQLTicketRepository(db)

    ticket = repository.update_status(
        ticket_id=ticket_id,
        status=data.status,
    )

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    return ticket