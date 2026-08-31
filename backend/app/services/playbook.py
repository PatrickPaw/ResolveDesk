import re

from app.ai.provider import AIProvider, AIProviderResponseError
from app.models.conversation import DiagnosticAnalysis, DiagnosticSnapshot, DiagnosticState, DiagnosticValue, FactEvidence
from app.models.incident import IncidentState
from app.models.resolution import ResolutionState, ResolutionStep
from app.models.playbook import Condition, EscalationPolicy, Playbook, PlaybookRule
from app.services.catalog import get_catalog, get_policy, select_profile


PLAYBOOKS = get_catalog()


def select_playbook(
    incident: IncidentState,
) -> Playbook | None:
    policy = get_policy()
    profile = select_profile(incident)
    if profile:
        family = incident.issue_family.value if incident.issue_family else ""
        return get_playbook(profile.family_overrides.get(family, profile.playbook_id))
                                                                            
                                                                              
                                                                               
    for subject in (incident.subcategory, incident.summary):
        matches = [
            playbook for playbook in PLAYBOOKS
            if incident.category in playbook.categories
            and any(
                re.search(r"(?<!\w)" + re.escape(normalize_text(alias)) + r"(?!\w)", normalize_text(subject))
                for alias in playbook.aliases
            )
        ]
        if matches:
            return matches[0] if len(matches) == 1 else None
    if incident.issue_family:
        return get_playbook(policy.family_playbooks.get(incident.issue_family.value))
    return None


def get_playbook(
    playbook_id: str | None,
) -> Playbook | None:
    if playbook_id is None:
        return None

    for playbook in PLAYBOOKS:
        if playbook.playbook_id == playbook_id:
            return playbook

    return None


def has_current_blocker(diagnostic: DiagnosticState) -> bool:
    playbook = get_playbook(diagnostic.playbook_id)
    if not playbook or diagnostic.current_message_id is None:
        return False
    fresh = {key: value for key, value in diagnostic.facts.items()
        if key in diagnostic.fact_evidence
        and diagnostic.fact_evidence[key].source_message_id == diagnostic.current_message_id
        and diagnostic.fact_evidence[key].status == "reported"}
    return any(condition_matches(condition, fresh) for condition in playbook.unresolved_conditions)


def start_diagnosis(
    incident: IncidentState,
    diagnostic: DiagnosticState,
) -> DiagnosticState:
    playbook = select_playbook(
        incident
    )

    if playbook is None or diagnostic.playbook_id != playbook.playbook_id:
        contexts = dict(diagnostic.contexts)
        if diagnostic.playbook_id:
            contexts[diagnostic.playbook_id] = DiagnosticSnapshot(
                catalog_version=diagnostic.catalog_version,
                facts=dict(diagnostic.facts), fact_evidence=dict(diagnostic.fact_evidence),
            )
        previous = contexts.pop(playbook.playbook_id, DiagnosticSnapshot()) if playbook else DiagnosticSnapshot()
        current = diagnostic.model_copy(update={
            "playbook_id": playbook.playbook_id if playbook else None,
            "catalog_version": previous.catalog_version,
            "facts": dict(previous.facts), "fact_evidence": dict(previous.fact_evidence),
            "contexts": contexts, "pending_fact": None,
        })
    else:
        current = diagnostic
    if playbook is None:
        return current
                                                                            
    shared = {
        key: value for key, value in incident.model_dump(exclude_none=True).items()
        if key in playbook.facts and key not in current.facts
    }
    return current.model_copy(update={
        "facts": {**current.facts, **shared},
        "catalog_version": current.catalog_version or playbook.version,
    })


def process_diagnostic_message(
    ai_provider: AIProvider,
    message: str,
    incident: IncidentState,
    diagnostic: DiagnosticState,
    last_question: str | None = None,
) -> tuple[DiagnosticState, DiagnosticAnalysis]:
    playbook = get_playbook(
        diagnostic.playbook_id
    )

    if playbook is None:
        raise ValueError(
            "Diagnostic message requires an active playbook."
        )

    analysis = ai_provider.analyze_diagnostic_response(
        message=message,
        incident=incident,
        diagnostic=diagnostic.model_copy(update={"contexts": {}, "fact_evidence": {}}),
        playbook_id=playbook.playbook_id,
        allowed_facts=playbook.facts,
        last_question=last_question,
    )

    unsupported = (set(analysis.facts) | set(analysis.uncertain_facts)) - set(playbook.facts)

    if unsupported:
        raise AIProviderResponseError(
            "Diagnostic analysis returned unsupported facts."
        )

    if not analysis.understood:
        return diagnostic, analysis

    for key, value in analysis.facts.items():
        if not playbook.fact_definitions[key].accepts(value):
            raise AIProviderResponseError(f"Invalid diagnostic fact type: {key}")

    facts = {
        **diagnostic.facts,
        **{key: value for key, value in analysis.facts.items() if key not in analysis.uncertain_facts},
    }

    pending_fact = diagnostic.pending_fact

    if pending_fact in analysis.facts:
        pending_fact = None

    updated = diagnostic.model_copy(
        update={
            "facts": facts,
            "pending_fact": pending_fact,
            "fact_evidence": {
                **diagnostic.fact_evidence,
                **{key: FactEvidence(source_message_id=diagnostic.current_message_id,
                    status="unknown" if value is None else "reported")
                   for key, value in analysis.facts.items() if key not in analysis.uncertain_facts},
                **{key: FactEvidence(source_message_id=diagnostic.current_message_id,
                    status="suspected", suspected_value=analysis.facts.get(key))
                   for key in analysis.uncertain_facts if key not in diagnostic.facts},
            },
            "pending_question": None if diagnostic.pending_question and diagnostic.pending_question.fact_key in analysis.facts else diagnostic.pending_question,
        }
    )

    return updated, analysis


def get_next_diagnostic_fact(
    diagnostic: DiagnosticState,
) -> str | None:
    playbook = get_playbook(
        diagnostic.playbook_id
    )

    if playbook is None:
        return None

    ready_rules = get_ready_rules(
        playbook=playbook,
        facts=diagnostic.facts,
    )

    if any(
        rule.actions
        for rule in ready_rules
    ):
        return None

    compatible_rules = [
        rule
        for rule in playbook.rules
        if rule.ask_missing_facts and rule_is_compatible(
            rule=rule,
            facts=diagnostic.facts,
        )
    ]

                                                                             
                                                                             
                                                                             
    compatible_rules.sort(key=lambda rule: sum(
        condition_matches(condition, diagnostic.facts)
        for condition in rule.conditions
    ), reverse=True)

    for rule in compatible_rules:
        missing = get_missing_rule_fact(
            playbook=playbook,
            rule=rule,
            facts=diagnostic.facts,
        )

        if missing is not None:
            return missing

    for fact_key in playbook.fallback_facts:
        if fact_key in diagnostic.facts:
            continue

        if fact_is_applicable(
            playbook=playbook,
            fact_key=fact_key,
            facts=diagnostic.facts,
        ):
            return fact_key

    return None


def get_next_playbook_action(
    diagnostic: DiagnosticState,
    resolution: ResolutionState,
) -> ResolutionStep | None:
    playbook = get_playbook(
        diagnostic.playbook_id
    )

    if playbook is None:
        return None

    attempted = {
        attempt.step.source_id
        for attempt in resolution.attempts
    }

    for rule in get_ready_rules(
        playbook=playbook,
        facts=diagnostic.facts,
    ):
        for action in rule.actions:
            source_id = (
                f"PLAYBOOK-{action.action_id}"
            )

            if source_id in attempted:
                continue
            if action.skip_conditions and all(condition_matches(c, diagnostic.facts) for c in action.skip_conditions):
                continue

            return ResolutionStep(
                instruction=action.instruction,
                source_id=source_id,
            )

    return None


def get_playbook_escalation(
    diagnostic: DiagnosticState, resolution: ResolutionState,
    *, exhausted: bool = False,
) -> EscalationPolicy | None:
                                                                                   
                                                                                  
    playbook = get_playbook(diagnostic.playbook_id)
    if playbook:
        for rule in playbook.rules:
            if rule.escalation and rule_matches(rule, diagnostic.facts):
                return rule.escalation
                                                                                    
    failed_sources = {
        attempt.step.source_id for attempt in resolution.attempts
        if attempt.problem_resolved is False or attempt.step_completed is False
    }
    blocked_sources = {attempt.step.source_id for attempt in resolution.attempts if attempt.step_completed is False}
    for playbook in PLAYBOOKS:
        for rule in playbook.rules:
            for action in rule.actions:
                if action.blocked_escalation and f"PLAYBOOK-{action.action_id}" in blocked_sources:
                    return action.blocked_escalation
                if action.failure_escalation and f"PLAYBOOK-{action.action_id}" in failed_sources:
                    return action.failure_escalation
    playbook = get_playbook(diagnostic.playbook_id)
    if playbook:
        for rule in playbook.rules:
            if rule_matches(rule, diagnostic.facts):
                if exhausted and rule.exhausted_escalation:
                    return rule.exhausted_escalation
    return None


def get_ready_rules(
    playbook: Playbook,
    facts: dict[str, DiagnosticValue],
) -> list[PlaybookRule]:
    return [
        rule
        for rule in playbook.rules
        if rule_matches(
            rule=rule,
            facts=facts,
        )
        and all(
            facts.get(fact_key) is not None
            for fact_key in rule.required_facts
        )
    ]


def get_missing_rule_fact(
    playbook: Playbook,
    rule: PlaybookRule,
    facts: dict[str, DiagnosticValue],
) -> str | None:
    for condition in rule.conditions:
        if condition_matches(
            condition=condition,
            facts=facts,
        ):
            continue

        for key in condition.keys:
            if key in facts:
                continue

            if fact_is_applicable(
                playbook=playbook,
                fact_key=key,
                facts=facts,
            ):
                return key

    for key in rule.required_facts:
        if key in facts:
            continue

        if fact_is_applicable(
            playbook=playbook,
            fact_key=key,
            facts=facts,
        ):
            return key

    return None


def rule_matches(
    rule: PlaybookRule,
    facts: dict[str, DiagnosticValue],
) -> bool:
    return all(
        condition_matches(
            condition=condition,
            facts=facts,
        )
        for condition in rule.conditions
    )


def rule_is_compatible(
    rule: PlaybookRule,
    facts: dict[str, DiagnosticValue],
) -> bool:
    return all(
        condition_is_compatible(
            condition=condition,
            facts=facts,
        )
        for condition in rule.conditions
    )


def condition_matches(
    condition: Condition,
    facts: dict[str, DiagnosticValue],
) -> bool:
    for key in condition.keys:
        if key not in facts:
            continue

        actual = facts[key]

        if any(
            value_matches(
                actual=actual,
                expected=expected,
                contains=condition.contains,
            )
            for expected in condition.values
        ):
            return True

    return False


def condition_is_compatible(
    condition: Condition,
    facts: dict[str, DiagnosticValue],
) -> bool:
    if condition_matches(
        condition=condition,
        facts=facts,
    ):
        return True

    return any(
        key not in facts
        for key in condition.keys
    )


def fact_is_applicable(
    playbook: Playbook,
    fact_key: str,
    facts: dict[str, DiagnosticValue],
) -> bool:
    conditions = playbook.fact_conditions.get(
        fact_key
    )

    if conditions is None:
        return True

    return all(
        condition_matches(
            condition=condition,
            facts=facts,
        )
        for condition in conditions
    )


def value_matches(
    actual: DiagnosticValue,
    expected: DiagnosticValue,
    contains: bool,
) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        normalized_actual = normalize_text(
            actual
        )

        normalized_expected = normalize_text(
            expected
        )

        if contains:
            return normalized_expected in normalized_actual

        return normalized_actual == normalized_expected

    return type(actual) is type(expected) and actual == expected


def normalize_text(
    value: str | None,
) -> str:
    if value is None:
        return ""

    return " ".join(
        value.strip().upper().split()
    )
