from dataclasses import dataclass
from hashlib import sha256
import hmac
import secrets
from threading import Lock
import time

from app.core.config import settings
from app.models.conversation import ConversationStage, ConversationState


TTL_SECONDS = 300
RESEND_SECONDS = 60
MAX_ATTEMPTS = 5
MAX_CHALLENGES = 1024


def demo_available(conversation: ConversationState) -> bool:
    return (
        settings.password_reset_demo_enabled
        and conversation.incident.password_forgotten is True
        and not conversation.security_emergency
        and conversation.stage == ConversationStage.ACTIVE
    )


class DemoCodeError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Challenge:
    conversation_id: str
    digest: bytes
    created_at: float
    attempts: int = 0
    consumed: bool = False


class DemoCodeStore:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.key = secrets.token_bytes(32)
        self.challenges: dict[str, Challenge] = {}
        self.lock = Lock()

    def digest(self, challenge_id: str, code: str) -> bytes:
        return hmac.new(self.key, f"{challenge_id}:{code}".encode(), sha256).digest()

    def issue(self, conversation_id: str) -> dict:
        with self.lock:
            now = self.clock()
            self.challenges = {
                key: value for key, value in self.challenges.items()
                if now - value.created_at < TTL_SECONDS
            }
            previous = [key for key, value in self.challenges.items() if value.conversation_id == conversation_id]
            if any(now - self.challenges[key].created_at < RESEND_SECONDS for key in previous):
                raise DemoCodeError(429, "Poczekaj minutę od ostatniego wysłania kodu demo.")
            if len(self.challenges) >= MAX_CHALLENGES and not previous:
                raise DemoCodeError(429, "Limit pokazów został osiągnięty. Spróbuj później.")
            for key in previous:
                del self.challenges[key]
            challenge_id = secrets.token_urlsafe(32)
            code = f"{secrets.randbelow(1_000_000):06d}"
            self.challenges[challenge_id] = Challenge(conversation_id, self.digest(challenge_id, code), now)
                                                                                     
                                                                                        
            return {
                "challenge_id": challenge_id, "demo_code": code,
                "expires_in_seconds": TTL_SECONDS, "retry_after_seconds": RESEND_SECONDS,
                "delivery": "SIMULATED_MAILBOX", "simulated": True,
            }

    def verify(self, conversation_id: str, challenge_id: str, code: str) -> None:
        with self.lock:
            item = self.challenges.get(challenge_id)
            if not item or item.conversation_id != conversation_id:
                raise DemoCodeError(410, "Kod demo nie istnieje lub został zastąpiony. Wygeneruj nowy.")
            if self.clock() - item.created_at >= TTL_SECONDS:
                raise DemoCodeError(410, "Kod demo wygasł. Wygeneruj nowy.")
            if item.consumed:
                raise DemoCodeError(410, "Ten kod demo został już wykorzystany.")
            if item.attempts >= MAX_ATTEMPTS:
                raise DemoCodeError(429, "Wyczerpano limit prób. Wygeneruj nowy kod demo.")
            item.attempts += 1
            if not hmac.compare_digest(item.digest, self.digest(challenge_id, code)):
                remaining = MAX_ATTEMPTS - item.attempts
                raise DemoCodeError(400 if remaining else 429, f"Nieprawidłowy kod demo. Pozostało prób: {remaining}.")
            item.consumed = True


demo_codes = DemoCodeStore()
