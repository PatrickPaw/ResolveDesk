from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.ai.ollama_provider import OllamaProvider
from app.api.access import Principal, get_principal
from app.ai.provider import AIProvider
from app.core.config import settings
from app.db.conversation_repository import PostgreSQLConversationRepository
from app.db.database import get_db
from app.db.models import ChatRequestRecord
from app.db.knowledge_repository import PostgreSQLKnowledgeRepository
from app.db.resolved_incident_repository import PostgreSQLResolvedIncidentRepository
from app.db.ticket_repository import PostgreSQLTicketRepository
from app.models.chat import ChatRequest, ChatResponse
from app.services.support import (
    ConversationClosedError, ConversationNotFoundError, SupportService,
)


router = APIRouter(tags=["Chat"])


@lru_cache
def get_ai_provider() -> AIProvider:
    return OllamaProvider()


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    ai: AIProvider = Depends(get_ai_provider),
    principal: Principal = Depends(get_principal),
) -> ChatResponse:
    receipt = None
    if request.request_id:
                                                                             
                                                                                 
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        key = str(request.request_id)
        db.execute(insert(ChatRequestRecord).values(request_id=key, owner_id=principal.subject,
            original_conversation_id=request.conversation_id).on_conflict_do_nothing(index_elements=["request_id"]))
        receipt = db.scalar(select(ChatRequestRecord).where(ChatRequestRecord.request_id == key).with_for_update())
        if receipt.owner_id != principal.subject:
            raise HTTPException(404, "Request not found.")
        if receipt.original_conversation_id != request.conversation_id:
            raise HTTPException(409, "Request identifier belongs to another turn.")
        if receipt.response is not None:
            return ChatResponse.model_validate(receipt.response)
    service = SupportService(
        ai=ai,
        conversations=PostgreSQLConversationRepository(db, principal.subject, principal.is_admin),
        knowledge=PostgreSQLKnowledgeRepository(db),
        tickets=PostgreSQLTicketRepository(db),
        resolved_incidents=PostgreSQLResolvedIncidentRepository(db),
        explain=(
            request.include_explainability
            and principal.is_admin
            and settings.explainability_trace_enabled
        ),
    )
    try:
        response = service.handle(request)
        if receipt is not None:
            receipt.response = response.model_dump(mode="json")
            db.flush()
        return response
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConversationClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
