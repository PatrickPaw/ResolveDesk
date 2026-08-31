from functools import wraps
from contextlib import contextmanager
from contextvars import ContextVar
import logging
from time import monotonic
from typing import Protocol

from app.models.conversation import (
    DiagnosticAnalysis,
    DiagnosticState,
    MessageAnalysis,
    MessageContext,
    SecurityAssessment,
)
from app.models.incident import IncidentState
from app.models.knowledge import KnowledgeArticle
from app.models.resolution import (
    ResolutionProposal,
    ResolutionState,
)


class AIProviderError(RuntimeError):
    operation: str | None = None


_deadline = ContextVar("ai_turn_deadline", default=None)
logger = logging.getLogger("resolvedesk.ai")


@contextmanager
def turn_budget(seconds: float):
    token = _deadline.set(monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_timeout(maximum: float) -> float:
    deadline = _deadline.get()
    remaining = maximum if deadline is None else min(maximum, deadline - monotonic())
    if remaining <= 0:
        raise AIProviderUnavailableError("AI turn time budget exhausted.")
    return remaining


def provider_operation(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        started = monotonic()
        try:
            return method(*args, **kwargs)
        except AIProviderError as exc:
            if exc.operation is None:
                exc.operation = method.__name__
            raise
        finally:
            logger.info("operation=%s duration_ms=%d", method.__name__, (monotonic() - started) * 1000)
    return wrapped


class AIProviderUnavailableError(AIProviderError):
    pass


class AIProviderResponseError(AIProviderError):
    pass


class AIProvider(Protocol):
    def analyze_message(self, message: str, context: MessageContext) -> MessageAnalysis:
        ...

    def assess_security_event(
        self, message: str, context: MessageContext,
    ) -> SecurityAssessment:
        ...

    def generate_it_explanation(
        self,
        message: str,
    ) -> str:
        ...


    def analyze_diagnostic_response(
        self,
        message: str,
        incident: IncidentState,
        diagnostic: DiagnosticState,
        playbook_id: str,
        allowed_facts: dict[str, str],
        last_question: str | None = None,
    ) -> DiagnosticAnalysis:
        ...


    def generate_resolution_step(
        self,
        incident: IncidentState,
        knowledge: list[KnowledgeArticle],
        resolution: ResolutionState,
    ) -> ResolutionProposal:
        ...


    def embed_query(
        self,
        text: str,
    ) -> list[float]:
        ...

    def embed_document(
        self,
        text: str,
    ) -> list[float]:
        ...
