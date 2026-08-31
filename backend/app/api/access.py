import hashlib
import json
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings


class Principal(BaseModel):
    subject: str = Field(min_length=1, max_length=100)
    role: Literal["EMPLOYEE", "ADMIN"] = "EMPLOYEE"

    @property
    def is_admin(self):
        return self.role == "ADMIN"


class TokenGrant(Principal):
    token_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


bearer = HTTPBearer(auto_error=False)


def get_principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
    if settings.access_mode == "demo":
        return Principal(subject="local-demo", role="ADMIN")
    if settings.access_mode != "token":
        raise HTTPException(503, "Access configuration is invalid.")
    try:
        grants = [TokenGrant.model_validate(item) for item in json.loads(settings.access_tokens)]
        if not grants or len({g.token_sha256 for g in grants}) != len(grants):
            raise ValueError("Invalid grants")
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(503, "Access configuration is invalid.") from None
    if credentials and credentials.scheme.lower() == "bearer":
        digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        for grant in grants:
            if secrets.compare_digest(digest, grant.token_sha256):
                return Principal(subject=grant.subject, role=grant.role)
    raise HTTPException(401, "Authentication required.", headers={"WWW-Authenticate": "Bearer"})


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(403, "Administrator access required.")
    return principal


router = APIRouter(prefix="/auth", tags=["Access"])


@router.get("/mode")
def access_mode():
    return {"authentication_required": settings.access_mode != "demo"}


@router.get("/me")
def current_principal(principal: Principal = Depends(get_principal)):
    return principal
