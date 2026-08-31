import re

from app.ai.provider import AIProvider, AIProviderResponseError
from app.models.conversation import (
    MessageClassification, MessageContext, MessageIntent, SecurityAssessment,
)


SENSITIVE_DATA_PATTERNS = (
    re.compile(r"\b(?:podaj[eę]|przesy[lł]am|wpisuj[eę])\s+(?:has[lł]o|password)\s+(?=\S*[0-9])(?=\S*[a-zA-Z])\S{4,}", re.I),
    re.compile(r"\b(?:hasło|haslo|password|passwd)\s*(?:to|is|:|=)\s*\S+", re.I),
    re.compile(r"\b(?:hasło|haslo|password|passwd)\s+jest\s+(?!(?:nie\s+)?(?:aktualne|nieaktualne|poprawne|niepoprawne|prawidłowe|nieprawidłowe|błędne|wygasłe|ważne|nieważne|zablokowane|zapomniane|nowe|stare|zmienione|dobre|złe)\b)\S+", re.I),
    re.compile(r"\b(?:kod\s+(?:mfa|otp|jednorazowy)|mfa|otp)\s*(?:to|jest|is|:|=)\s*[A-Za-z0-9-]{4,}\b", re.I),
    re.compile(r"\b(?:api[\s_-]?key|token)\s*(?:to|jest|is|:|=)\s*\S+", re.I),
)

REDACTED_MESSAGE = (
    "[REDACTED] Wiadomość zawierała dane uwierzytelniające "
    "i nie została zapisana w oryginalnej formie."
)


def contains_explicit_sensitive_data(message: str) -> bool:
    return any(pattern.search(message) for pattern in SENSITIVE_DATA_PATTERNS)


def validate_security_assessment(assessment: SecurityAssessment, message: str) -> None:
    if assessment.event_type is None:
        if assessment.evidence or assessment.contains_secret:
            raise AIProviderResponseError("Security assessment is inconsistent.")
        return
    evidence = (assessment.evidence or "").strip()
    if not evidence or evidence not in message:
        raise AIProviderResponseError("Security assessment lacks evidence from the current message.")


def verify_security_signal(
    ai: AIProvider, message: str, context: MessageContext,
    classification: MessageClassification,
) -> SecurityAssessment | None:
    suspected = (
        classification.intent == MessageIntent.SECURITY_INCIDENT
        or classification.security_emergency
        or classification.sensitive_data_detected
    )
    if not suspected:
        return None

    assessment = ai.assess_security_event(message, context)
    validate_security_assessment(assessment, message)
    return assessment if assessment.event_type is not None else None
