from app.models.conversation import ConversationState
from app.models.ticket import EscalationTicket
from app.models.routing import TicketRouting
from app.models.playbook import EscalationPolicy
from app.services.catalog import select_profile


def create_escalation_ticket(
    conversation: ConversationState,
    escalation_reason: str,
    policy: EscalationPolicy | None = None,
) -> EscalationTicket:
    routing = TicketRouting(
        playbook_id=conversation.diagnostic.playbook_id,
        catalog_version=conversation.diagnostic.catalog_version,
    )
    if policy:
        routing = routing.model_copy(update={key: getattr(policy, key) for key in ("ticket_kind", "queue", "reason_code")})
    profile = select_profile(conversation.incident)
    if profile and routing.queue == "IT_SUPPORT":
        routing = routing.model_copy(update={"queue": profile.queue})
    if conversation.security_emergency:
        routing = routing.model_copy(update={"ticket_kind": "SECURITY", "queue": "SECURITY", "reason_code": "SECURITY_EVENT"})
    elif conversation.incident.password_forgotten:
        routing = routing.model_copy(update={"ticket_kind": "ACCESS_REQUEST", "queue": "ACCESS", "reason_code": "PASSWORD_RECOVERY"})
    return EscalationTicket(
        conversation_id=conversation.conversation_id,
        incident=conversation.incident,
        diagnostic=conversation.diagnostic,
        resolution_attempts=conversation.resolution.attempts,
        escalation_reason=escalation_reason,
        routing=routing,
    )
