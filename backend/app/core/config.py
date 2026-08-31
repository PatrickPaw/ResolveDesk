import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(
    PROJECT_ROOT / ".env"
)


class Settings:
    ai_call_timeout: float = float(os.getenv("AI_CALL_TIMEOUT_SECONDS", "45"))
    ai_turn_timeout: float = float(os.getenv("AI_TURN_TIMEOUT_SECONDS", "90"))
    if not (0 < ai_call_timeout < float("inf") and 0 < ai_turn_timeout < float("inf")):
        raise ValueError("AI timeouts must be positive finite values")
    access_mode: str = os.getenv("RESOLVEDESK_ACCESS_MODE", "demo").strip().lower()
    access_tokens: str = os.getenv("RESOLVEDESK_ACCESS_TOKENS", "[]")
    password_reset_demo_enabled: bool = os.getenv("PASSWORD_RESET_DEMO_ENABLED", "false").strip().lower() in {"true", "1", "yes"}
    explainability_trace_enabled: bool = os.getenv(
        "EXPLAINABILITY_TRACE_ENABLED", "false"
    ).strip().lower() in {"true", "1", "yes"}

    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://resolvedesk:resolvedesk@localhost:5433/resolvedesk",
    )

    ollama_host: str = os.getenv(
        "OLLAMA_HOST",
        "http://localhost:11434",
    )

    ollama_model: str = os.getenv(
        "OLLAMA_MODEL",
        "qwen3:8b",
    )
    ollama_think: bool = os.getenv("OLLAMA_THINK", "true").strip().lower() in {"true", "1", "yes"}

    ollama_embedding_model: str = os.getenv(
        "OLLAMA_EMBEDDING_MODEL",
        "nomic-embed-text-v2-moe",
    )


settings = Settings()
