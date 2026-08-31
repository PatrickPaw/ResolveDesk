from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.api.chat import get_ai_provider
from app.api.access import Principal, get_principal
from app.db.database import get_db
from app.db.models import MessageRecord, ChatRequestRecord
from app.ai.provider import AIProviderUnavailableError
from app.core.config import settings


def test_chat_contract_transaction_and_retry(chat):
    def db_override():
        with Session(chat.engine) as db, db.begin():
            yield db
    app.dependency_overrides[get_db]=db_override
    app.dependency_overrides[get_ai_provider]=lambda:chat.ai
    app.dependency_overrides[get_principal]=lambda:Principal(subject="local-demo",role="ADMIN")
    try:
        with TestClient(app) as client:
            chat.ai.messages.append(AIProviderUnavailableError("read timeout"))
            request={"message":"Nie działa monitor", "request_id":str(uuid4())}
            failed=client.post("/chat",json=request)
            assert failed.status_code==503 and failed.json()["code"]=="AI_UNAVAILABLE"
            with Session(chat.engine) as db:
                assert not list(db.scalars(select(MessageRecord)))
                assert not list(db.scalars(select(ChatRequestRecord)))
            chat.ai.expect(incident={"category":"HARDWARE","subcategory":"MONITOR","summary":"Nie działa monitor","issue_family":"DEVICE"},facts={})
            response=client.post("/chat",json=request)
            assert response.status_code==200
            assert {"conversation_id","stage","reply","incident","ticket_id","password_reset_demo_available"} <= response.json().keys()
            assert response.headers["cache-control"]=="no-store"
            calls=list(chat.ai.calls)
            duplicate=client.post("/chat",json=request)
            assert duplicate.json()==response.json() and chat.ai.calls==calls
    finally:
        app.dependency_overrides.clear()


def test_explainability_is_not_returned_to_non_admin_api_client(chat, monkeypatch):
    def db_override():
        with Session(chat.engine) as db, db.begin():
            yield db
    monkeypatch.setattr(settings, "explainability_trace_enabled", True)
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_ai_provider] = lambda: chat.ai
    app.dependency_overrides[get_principal] = lambda: Principal(subject="employee", role="EMPLOYEE")
    chat.ai.expect(
        incident={
            "category": "HARDWARE", "subcategory": "MONITOR",
            "summary": "Nie działa monitor", "issue_family": "DEVICE",
        },
        facts={},
    )
    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={
                "message": "Nie działa monitor",
                "include_explainability": True,
            })
            assert response.status_code == 200
            assert response.json()["explainability"] is None
    finally:
        app.dependency_overrides.clear()
