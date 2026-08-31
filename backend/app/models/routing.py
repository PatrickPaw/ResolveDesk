from typing import Literal

from pydantic import BaseModel


class TicketRouting(BaseModel):
    ticket_kind: Literal["INCIDENT", "SERVICE_REQUEST", "ACCESS_REQUEST", "SECURITY"] = "INCIDENT"
    queue: str = "IT_SUPPORT"
    reason_code: str = "L1_EXHAUSTED"
    playbook_id: str | None = None
    catalog_version: str | None = None
    delivery_status: Literal["LOCAL_ONLY"] = "LOCAL_ONLY"
