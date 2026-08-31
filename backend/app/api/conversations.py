from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.conversation_repository import PostgreSQLConversationRepository
from app.api.access import Principal, get_principal
from app.db.database import get_db
from app.db.ticket_repository import PostgreSQLTicketRepository
from app.models.conversation import ConversationState
from app.services.password_reset_demo import demo_available


router = APIRouter(
    prefix="/conversations",
    tags=["Conversations"],
)


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class ConversationResponse(ConversationState):
    ticket_id: str | None = None
    password_reset_demo_available: bool = False


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    repository = PostgreSQLConversationRepository(db, principal.subject, principal.is_admin)

    conversation = repository.get(
        conversation_id
    )

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    ticket = PostgreSQLTicketRepository(db).get_by_conversation_id(conversation_id)
    return ConversationResponse(
        **conversation.model_dump(),
        ticket_id=ticket.ticket_id if ticket else None,
        password_reset_demo_available=demo_available(conversation),
    )


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
def get_conversation_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    repository = PostgreSQLConversationRepository(db, principal.subject, principal.is_admin)

    conversation = repository.get(
        conversation_id
    )

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    messages = repository.get_messages(
        conversation_id
    )

    return [
        MessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        )
        for message in messages
    ]
