from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.api.access import Principal, get_principal
from app.db.conversation_repository import PostgreSQLConversationRepository
from app.db.database import get_db
from app.services.password_reset_demo import DemoCodeError, demo_available, demo_codes

router = APIRouter(prefix="/demo/password-reset", tags=["Presentation only"])

class DemoRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=100)


class DemoVerification(DemoRequest):
    challenge_id: str = Field(min_length=1, max_length=100)
    code: str = Field(pattern=r"^[0-9]{6}$")


def require_demo(request: DemoRequest, db: Session, principal: Principal) -> None:
    if not settings.password_reset_demo_enabled:
        raise HTTPException(404, "Tryb demonstracyjny jest wyłączony.")
    conversation = PostgreSQLConversationRepository(db, principal.subject, principal.is_admin).get(request.conversation_id)
    if conversation is None:
        raise HTTPException(404, "Rozmowa nie istnieje.")
    if not demo_available(conversation):
        raise HTTPException(409, "Pokaz nie jest dostępny w tej rozmowie.")


@router.post("/request")
def request_demo_code(request: DemoRequest, response: Response, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    response.headers["Cache-Control"] = "no-store"
    require_demo(request, db, principal)
    try:
        return demo_codes.issue(request.conversation_id)
    except DemoCodeError as exc:
        raise HTTPException(exc.status, str(exc), headers={"Cache-Control": "no-store"}) from exc


@router.post("/verify")
def verify_demo_code(request: DemoVerification, response: Response, db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    response.headers["Cache-Control"] = "no-store"
    require_demo(request, db, principal)
    try:
        demo_codes.verify(request.conversation_id, request.challenge_id, request.code)
    except DemoCodeError as exc:
        raise HTTPException(exc.status, str(exc), headers={"Cache-Control": "no-store"}) from exc
    return {
        "verified": True, "simulated": True,
        "message": "Kod demo został potwierdzony i zużyty. Pokaz zakończony. Żadne hasło firmowe nie zostało zmienione.",
    }
