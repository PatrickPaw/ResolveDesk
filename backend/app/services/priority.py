from app.models.incident import (
    AffectedScope,
    Impact,
    IncidentState,
    Priority,
    Urgency,
)


PRIORITY_MATRIX = {
    (Impact.LOW, Urgency.LOW): Priority.P4,
    (Impact.LOW, Urgency.MEDIUM): Priority.P4,
    (Impact.LOW, Urgency.HIGH): Priority.P3,
    (Impact.LOW, Urgency.CRITICAL): Priority.P3,

    (Impact.MEDIUM, Urgency.LOW): Priority.P4,
    (Impact.MEDIUM, Urgency.MEDIUM): Priority.P3,
    (Impact.MEDIUM, Urgency.HIGH): Priority.P2,
    (Impact.MEDIUM, Urgency.CRITICAL): Priority.P2,

    (Impact.HIGH, Urgency.LOW): Priority.P3,
    (Impact.HIGH, Urgency.MEDIUM): Priority.P2,
    (Impact.HIGH, Urgency.HIGH): Priority.P1,
    (Impact.HIGH, Urgency.CRITICAL): Priority.P1,

    (Impact.CRITICAL, Urgency.LOW): Priority.P2,
    (Impact.CRITICAL, Urgency.MEDIUM): Priority.P1,
    (Impact.CRITICAL, Urgency.HIGH): Priority.P1,
    (Impact.CRITICAL, Urgency.CRITICAL): Priority.P1,
}


def calculate_priority(
    impact: Impact,
    urgency: Urgency,
) -> Priority:
    return PRIORITY_MATRIX[(impact, urgency)]


def determine_impact(
    incident: IncidentState,
) -> Impact | None:
    if (
        incident.affected_scope is None
        or incident.work_blocked is None
    ):
        return None

    if incident.work_blocked is False:
        return {
            AffectedScope.SINGLE_USER: Impact.LOW,
            AffectedScope.MULTIPLE_USERS: Impact.MEDIUM,
            AffectedScope.DEPARTMENT: Impact.MEDIUM,
            AffectedScope.ORGANIZATION: Impact.HIGH,
        }[incident.affected_scope]

    if incident.workaround_available is None:
        return None

    if incident.workaround_available is True:
        return {
            AffectedScope.SINGLE_USER: Impact.LOW,
            AffectedScope.MULTIPLE_USERS: Impact.MEDIUM,
            AffectedScope.DEPARTMENT: Impact.HIGH,
            AffectedScope.ORGANIZATION: Impact.HIGH,
        }[incident.affected_scope]

    return {
        AffectedScope.SINGLE_USER: Impact.MEDIUM,
        AffectedScope.MULTIPLE_USERS: Impact.HIGH,
        AffectedScope.DEPARTMENT: Impact.CRITICAL,
        AffectedScope.ORGANIZATION: Impact.CRITICAL,
    }[incident.affected_scope]


def determine_urgency(
    incident: IncidentState,
) -> Urgency | None:
    if (
        incident.customer_waiting is None
        and incident.time_pressure is None
    ):
        return None

    if (
        incident.customer_waiting is True
        or incident.time_pressure is True
    ):
        return Urgency.HIGH

    if incident.work_blocked is True:
        return Urgency.MEDIUM

    return Urgency.LOW


def determine_priority(
    incident: IncidentState,
) -> Priority | None:
    impact = determine_impact(
        incident
    )

    urgency = determine_urgency(
        incident
    )

    if impact is None or urgency is None:
        return None

    return calculate_priority(
        impact=impact,
        urgency=urgency,
    )