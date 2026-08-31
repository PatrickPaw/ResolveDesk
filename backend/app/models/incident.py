from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


class Category(str, Enum):
    ACCOUNT_ACCESS = "ACCOUNT_ACCESS"
    NETWORK = "NETWORK"
    HARDWARE = "HARDWARE"
    SOFTWARE = "SOFTWARE"
    EMAIL = "EMAIL"
    SECURITY = "SECURITY"
    OTHER = "OTHER"


class IssueFamily(str, Enum):
    DEVICE = "DEVICE"
    PRINTING = "PRINTING"
    NETWORK = "NETWORK"
    ACCESS = "ACCESS"
    APPLICATION = "APPLICATION"
    INTEGRATION = "INTEGRATION"
    PAYMENTS = "PAYMENTS"
    BUSINESS_DATA = "BUSINESS_DATA"
    RECOVERY = "RECOVERY"
    SECURITY = "SECURITY"


class AffectedScope(str, Enum):
    SINGLE_USER = "SINGLE_USER"
    MULTIPLE_USERS = "MULTIPLE_USERS"
    DEPARTMENT = "DEPARTMENT"
    ORGANIZATION = "ORGANIZATION"


class Impact(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Urgency(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class IncidentAnalysis(BaseModel):
    category: Category | None = None
    subcategory: str | None = None
    summary: str | None = Field(default=None, max_length=400)
    issue_family: IssueFamily | None = None
    service_profile: str | None = None

    affected_scope: AffectedScope | None = None
    affected_users: int | None = None

    work_blocked: bool | None = None

    workaround_available: bool | None = None
    workaround_description: str | None = None

    customer_waiting: bool | None = None
    time_pressure: bool | None = None

    error_message: str | None = None
    physical_hazard: bool | None = Field(default=None, description="An explicitly reported current physical hazard: smoke, burning smell, swelling, liquid spill or damaged electrical parts. An ordinary malfunction is not a hazard.")
    password_forgotten: bool | None = Field(
        default=None,
        description="True only when the user explicitly says they forgot or do not know their password. A failed login or an expired password alone is not enough. Never include the password itself.",
    )
    technical_observations: list[Annotated[str, Field(max_length=240)]] | None = Field(
        default=None,
        max_length=3,
        description="New technical observations or explicitly suspected causes, preserving uncertainty. Exclude business needs and facts already recorded. Never include credentials.",
    )


class IncidentState(IncidentAnalysis):
    technical_observations: list[str] = Field(default_factory=list)
    impact: Impact | None = None
    urgency: Urgency | None = None
    priority: Priority | None = None
    resolved: bool = False
