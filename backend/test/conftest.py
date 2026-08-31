from collections import deque

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.conversation_repository import PostgreSQLConversationRepository
from app.db.resolved_incident_repository import PostgreSQLResolvedIncidentRepository
from app.db.ticket_repository import PostgreSQLTicketRepository
from app.models.chat import ChatRequest
from app.models.conversation import MessageAnalysis, MessageClassification, DiagnosticAnalysis
from app.services.support import SupportService


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires local Ollama")


class ScriptedAI:
    def __init__(self):
        self.messages = deque()
        self.diagnostics = deque()
        self.calls = []
        self.security = None

    def expect(self, *, incident=None, facts=None, feedback=None, evidence=None, classification=None, uncertain=()):
        self.messages.append(MessageAnalysis(
            classification=classification or MessageClassification(intent="INCIDENT"),
            incident=incident or {}, feedback=feedback or {"understood": True},
            outcome_scope="ORIGINAL_PROBLEM" if feedback and feedback.get("problem_resolved") is not None else "STEP_ONLY" if feedback and feedback.get("step_completed") is not None else "UNSPECIFIED",
            resolution_evidence=evidence,
        ))
        if facts is not None:
            self.diagnostics.append(DiagnosticAnalysis(understood=True, facts=facts, uncertain_facts=list(uncertain)))

    def analyze_message(self, message, context):
        self.calls.append("interpret")
        value = self.messages.popleft()
        if isinstance(value, Exception):
            raise value
        return value

    def analyze_diagnostic_response(self, **kwargs):
        self.calls.append("diagnostic")
        return self.diagnostics.popleft()

    def assess_security_event(self, message, context):
        self.calls.append("security")
        return self.security

    def embed_query(self, text):
        self.calls.append("embed")
        return [0.0] * 768


class EmptyKnowledge:
    def search(self, **kwargs):
        return []


class ChatHarness:
    def __init__(self, engine, ai):
        self.engine, self.ai, self.conversation_id = engine, ai, None

    def send(self, message, *, explain=False):
        with Session(self.engine) as db, db.begin():
            service = SupportService(self.ai, PostgreSQLConversationRepository(db),
                EmptyKnowledge(), PostgreSQLTicketRepository(db), PostgreSQLResolvedIncidentRepository(db),
                explain=explain)
            response = service.handle(ChatRequest(message=message, conversation_id=self.conversation_id))
            self.conversation_id = response.conversation_id
            return response

    def state(self):
        with Session(self.engine) as db:
            return PostgreSQLConversationRepository(db).get(self.conversation_id)

    def seed(self, state):
        with Session(self.engine) as db, db.begin():
            repo = PostgreSQLConversationRepository(db)
            created = repo.create()
            state.conversation_id = created.conversation_id
            repo.save(state)
            self.conversation_id = created.conversation_id


@pytest.fixture
def chat():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield ChatHarness(engine, ScriptedAI())
    engine.dispose()
