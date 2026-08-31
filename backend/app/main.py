import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.ai.provider import (
    AIProviderResponseError,
    AIProviderUnavailableError,
)
from app.api.access import router as access_router
from app.services.catalog import get_policy
from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.knowledge import router as knowledge_router
from app.api.resolved_incidents import router as resolved_incidents_router
from app.api.tickets import router as tickets_router
from app.api.password_reset_demo import router as password_reset_demo_router
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("resolvedesk.api")
service_logger = logging.getLogger("resolvedesk")
service_logger.setLevel(logging.INFO)
if not service_logger.handlers:
    service_logger.addHandler(logging.StreamHandler())
service_logger.propagate = False


def service_error_response(status: int, code: str, detail: str, exc: Exception):
    request_id = str(uuid4())
    logger.error(
        "request_id=%s code=%s operation=%s error_type=%s cause_type=%s",
        request_id, code, getattr(exc, "operation", None) or (
            "database" if isinstance(exc, SQLAlchemyError) else "unknown"
        ),
        type(exc).__name__, type(exc.__cause__).__name__ if exc.__cause__ else "none",
    )
    return JSONResponse(status_code=status, content={
        "detail": detail, "code": code, "request_id": request_id,
    })

app = FastAPI(
    title="ResolveDesk API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

get_policy()
app.include_router(access_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(knowledge_router)
app.include_router(resolved_incidents_router)
app.include_router(tickets_router)
app.include_router(password_reset_demo_router)


@app.middleware("http")
async def no_private_response_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path != "/health":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(AIProviderUnavailableError)
async def handle_ai_provider_unavailable(
    _request: Request,
    _exc: AIProviderUnavailableError,
):
    return service_error_response(
        503, "AI_UNAVAILABLE", "AI service is temporarily unavailable.", _exc,
    )


@app.exception_handler(AIProviderResponseError)
async def handle_ai_provider_response_error(
    _request: Request,
    _exc: AIProviderResponseError,
):
    return service_error_response(
        502, "AI_INVALID_RESPONSE", "AI service returned an invalid response.", _exc,
    )


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(
    _request: Request,
    _exc: SQLAlchemyError,
):
    return service_error_response(
        503, "DATABASE_UNAVAILABLE", "Database service is temporarily unavailable.", _exc,
    )


@app.get("/health")
def health_check():
    return {
        "status": "ok"
    }
