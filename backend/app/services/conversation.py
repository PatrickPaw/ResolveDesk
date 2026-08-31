from dataclasses import dataclass
from enum import Enum

from app.models.conversation import (
    ConversationStage, ConversationState, DiagnosticState,
    MessageClassification, MessageIntent,
    PendingQuestion,
)
from app.models.incident import AffectedScope, IncidentAnalysis, IncidentState
from app.models.resolution import ResolutionFeedback, ResolutionOutcome, ResolutionStep
from app.services.playbook import (
    get_next_diagnostic_fact, get_next_playbook_action, get_playbook_escalation, start_diagnosis, get_playbook,
)
from app.models.playbook import EscalationPolicy
from app.services.catalog import select_profile, normalized_subject


class TriageNeed(str, Enum):
    PROBLEM_DESCRIPTION = "problem_description"
    AFFECTED_SCOPE = "affected_scope"
    WORK_IMPACT = "work_impact"
    WORKAROUND = "workaround"
    URGENCY_CONTEXT = "urgency_context"


                                                                            
                                                                            
TRIAGE_QUESTIONS = {
    TriageNeed.PROBLEM_DESCRIPTION: ("summary", "Opisz, co nie działa i jakiego urządzenia lub programu dotyczy problem."),
    TriageNeed.AFFECTED_SCOPE: ("affected_scope", "Czy ten problem dotyczy tylko Ciebie, czy również innych osób? Jeśli nie wiesz, napisz to."),
    TriageNeed.WORK_IMPACT: ("work_blocked", "Czy ten problem blokuje wykonanie Twojej pracy?"),
    TriageNeed.WORKAROUND: ("workaround_available", "Czy masz teraz inny sposób, żeby wykonać tę czynność?"),
    TriageNeed.URGENCY_CONTEXT: ("time_pressure", "Czy sprawa jest pilna z powodu bliskiego terminu lub oczekującego klienta?"),
}
TRIAGE_BOOLEAN_FIELDS = {"work_blocked", "workaround_available", "time_pressure"}
TECHNICAL_HINT_ACKNOWLEDGEMENT = (
    "Uwzględniłem nową wskazówkę, ale nie znalazłem zatwierdzonego "
    "kroku naprawczego, który mogę bezpiecznie zaproponować. "
)


def parse_short_answer(message: str) -> bool | None:
    return {"tak": True, "nie": False}.get(message.strip().casefold().rstrip(".!?"))


def short_triage_answer(message: str, last_question: str | None) -> IncidentAnalysis | None:
    value = parse_short_answer(message)
    if value is None or not last_question:
        return None
    question = last_question.removeprefix(TECHNICAL_HINT_ACKNOWLEDGEMENT).strip()
    for field, expected in TRIAGE_QUESTIONS.values():
        if field in TRIAGE_BOOLEAN_FIELDS and question == expected:
            return IncidentAnalysis(**{field: value})
    return None


class SupportDecisionType(str, Enum):
    ASK_TRIAGE = "ASK_TRIAGE"
    ASK_DIAGNOSTIC = "ASK_DIAGNOSTIC"
    ASK_FEEDBACK = "ASK_FEEDBACK"
    CLARIFY_STEP = "CLARIFY_STEP"
    PLAYBOOK_ACTION = "PLAYBOOK_ACTION"
    SEARCH_KNOWLEDGE = "SEARCH_KNOWLEDGE"
    RESOLVED = "RESOLVED"
    ESCALATE = "ESCALATE"
    EXPLAIN_IT = "EXPLAIN_IT"
    REPLY = "REPLY"
    DEMO_PASSWORD_RESET = "DEMO_PASSWORD_RESET"


@dataclass(frozen=True)
class SupportDecision:
    decision_type: SupportDecisionType
    diagnostic: DiagnosticState
    triage_need: TriageNeed | None = None
    diagnostic_fact: str | None = None
    resolution_step: ResolutionStep | None = None
    reply: str | None = None
    escalation_reason: str | None = None
    escalation_policy: EscalationPolicy | None = None
    pending_question: PendingQuestion | None = None


def ask_question(conversation, diagnostic, kind, question, **kwargs) -> SupportDecision:
    if diagnostic.question_attempts.get(question.question_id, 0) >= 2:
        return SupportDecision(
            SupportDecisionType.ESCALATE, diagnostic,
            escalation_reason=f"Unable to establish {question.question_id} after two questions.",
            escalation_policy=EscalationPolicy(reason="Required information unavailable.",
                reply="", reason_code="QUESTION_LIMIT"),
            reply="Nie będę powtarzać tego samego pytania. Utworzyłem zgłoszenie z zebranymi informacjami i zaznaczonym brakiem danych.",
        )
    return SupportDecision(kind, diagnostic, pending_question=question, **kwargs)


def bound_short_answer(conversation: ConversationState, message: str):
    question = conversation.diagnostic.pending_question
    value = parse_short_answer(message)
    if question and question.answer_type == "boolean" and value is not None:
        return question, value
    if question and question.target == "diagnostic":
        playbook = get_playbook(conversation.diagnostic.playbook_id)
        spec = playbook.fact_definitions.get(question.fact_key) if playbook else None
        if spec:
            answers = {normalized_subject(item): item for item in spec.allowed_values}
            answers.update({normalized_subject(key): value for key, value in spec.answer_aliases.items()})
            value = answers.get(normalized_subject(message).rstrip(".!?"))
            if value is not None:
                return question, value
    return None


def merge_incident_analysis(
    current: IncidentState, analysis: IncidentAnalysis,
) -> IncidentState:
    updates = analysis.model_dump(exclude_none=True)
    if analysis.technical_observations is not None:
        observations = list(current.technical_observations)
        seen = {" ".join(item.split()).casefold() for item in observations}
        for item in analysis.technical_observations:
            item = " ".join(item.split())
            if item and item.casefold() not in seen:
                observations.append(item)
                seen.add(item.casefold())
        updates["technical_observations"] = observations[-12:]
    if analysis.affected_scope is not None:
        if analysis.affected_scope == AffectedScope.SINGLE_USER:
            updates["affected_users"] = 1
        elif (
            analysis.affected_scope != current.affected_scope
            and analysis.affected_users is None
        ):
            updates["affected_users"] = None
    if analysis.workaround_available is False:
        updates["workaround_description"] = None
    return current.model_copy(update=updates)


def get_initial_triage_need(incident: IncidentState) -> TriageNeed | None:
    if not incident.category or not incident.summary:
        return TriageNeed.PROBLEM_DESCRIPTION
    if incident.affected_scope is None:
        return TriageNeed.AFFECTED_SCOPE
    return None


def get_escalation_triage_need(incident: IncidentState) -> TriageNeed | None:
    if incident.work_blocked is None:
        return TriageNeed.WORK_IMPACT
    if incident.work_blocked is True and incident.workaround_available is None:
        return TriageNeed.WORKAROUND
    if incident.customer_waiting is None and incident.time_pressure is None:
        return TriageNeed.URGENCY_CONTEXT
    return None


def get_next_triage_need(incident: IncidentState) -> TriageNeed | None:
    return get_initial_triage_need(incident) or get_escalation_triage_need(incident)


def decide_next_support_action(
    conversation: ConversationState,
    classification: MessageClassification | None = None,
    feedback: ResolutionFeedback | None = None,
    input_withheld: bool = False,
    technical_context_changed: bool = False,
    password_reset_demo_enabled: bool = False,
) -> SupportDecision:
    diagnostic = conversation.diagnostic
    incident = conversation.incident
    resolution = conversation.resolution

                                                                         
    if conversation.security_emergency:
        guidance = {
            "PHISHING": "Nie otwieraj ponownie podejrzanego linku ani załączników, nie instaluj oprogramowania z tej strony i nie podawaj na niej danych. Poczekaj na instrukcje IT/Security. ",
            "MALWARE": "Nie uruchamiaj podejrzanych plików ani nie instaluj narzędzi naprawczych. Poczekaj na instrukcje IT/Security. ",
            "UNEXPECTED_MFA": "Nie zatwierdzaj logowania, którego nie rozpoczynałeś. ",
            "DATA_DISCLOSURE": "Nie przesyłaj dalej ujawnionych danych i nie wklejaj ich do czatu. ",
        }.get(incident.subcategory, "")
        return SupportDecision(
            SupportDecisionType.ESCALATE, diagnostic,
            escalation_reason="Potential information security incident. Immediate IT/Security review required.",
            reply=(
                "Zgłoszenie zostało przekazane do IT/Security jako incydent bezpieczeństwa. "
                + guidance + "Nie wpisuj tutaj haseł, kodów MFA ani innych danych uwierzytelniających."
            ),
        )

    if input_withheld:
        return SupportDecision(
            SupportDecisionType.REPLY, diagnostic,
            reply=(
                "Nie zapisuję treści tej wiadomości, bo mogła zawierać dane uwierzytelniające. "
                "Opisz proszę wynik sprawdzenia bez haseł, kodów i tokenów."
            ),
        )

    if incident.physical_hazard is True:
        reply = "Przerwij używanie urządzenia. Nie dotykaj uszkodzonych elementów ani nie rozbieraj obudowy. Przekazałem zgłoszenie do IT. Przy dymie lub ogniu odsuń się i skorzystaj z firmowej procedury alarmowej."
        return SupportDecision(
            SupportDecisionType.ESCALATE, diagnostic, reply=reply,
            escalation_reason="Reported physical hazard requires IT review.",
            escalation_policy=EscalationPolicy(reason="Physical hazard", reply=reply,
                reason_code="PHYSICAL_HAZARD", queue="EQUIPMENT", safety_stop=True),
        )

    if (
        classification is not None
        and incident.category is None
        and incident.summary is None
        and not resolution.attempts
    ):
        if classification.intent == MessageIntent.OFF_TOPIC:
            return SupportDecision(
                SupportDecisionType.REPLY, diagnostic,
                reply="Zajmuję się wsparciem IT i bezpieczeństwem informacji. Opisz problem lub pytanie dotyczące firmowego IT.",
            )
        if classification.intent == MessageIntent.IT_EXPLANATION:
            return SupportDecision(SupportDecisionType.EXPLAIN_IT, diagnostic)

                                                                              
                                                                              
    diagnostic = start_diagnosis(incident, diagnostic)
    playbook = get_playbook(diagnostic.playbook_id)
    if playbook and diagnostic.catalog_version != playbook.version:
        return SupportDecision(
            SupportDecisionType.ESCALATE, diagnostic,
            escalation_reason="The conversation references an unavailable catalog version.",
            reply="Procedura tej rozmowy wymaga weryfikacji po aktualizacji. Utworzyłem zgłoszenie z dotychczasowym przebiegiem, bez ponawiania wykonanych kroków.",
        )
    handoff = get_playbook_escalation(diagnostic, resolution)
    if resolution.outcome == ResolutionOutcome.RESOLVED and not (handoff and handoff.safety_stop):
        return SupportDecision(SupportDecisionType.RESOLVED, diagnostic)
    if incident.password_forgotten is True and not (handoff and handoff.safety_stop):
        if password_reset_demo_enabled:
            return SupportDecision(
                SupportDecisionType.DEMO_PASSWORD_RESET, diagnostic,
                reply=(
                    "Możemy pokazać odzyskiwanie hasła w trybie demonstracyjnym. "
                    "Użyj formularza poniżej, aby wygenerować i odebrać jednorazowy kod "
                    "w symulowanej skrzynce. Nie wysyłam prawdziwego maila ani nie zmieniam "
                    "hasła firmowego. Kodu nie wpisuj w czacie."
                ),
            )
        return SupportDecision(
            SupportDecisionType.ESCALATE, diagnostic,
            escalation_reason="User forgot their password; identity verification and approved account recovery require IT.",
            reply="Przekazałem zgłoszenie odzyskania dostępu do IT. Nie zgaduj kolejnych haseł i nie wpisuj tutaj haseł ani kodów.",
        )

    if handoff:
        return SupportDecision(
            SupportDecisionType.ESCALATE, diagnostic,
            escalation_reason=handoff.reason, reply=handoff.reply, escalation_policy=handoff,
        )

    if conversation.stage == ConversationStage.RESOLUTION and resolution.attempts:
        pending = diagnostic.pending_question
        if (
            pending and pending.target == "diagnostic"
            and not technical_context_changed
            and not (feedback and feedback.clarification_requested)
        ):
                                                                              
                                                                                 
            return ask_question(conversation, diagnostic, SupportDecisionType.ASK_DIAGNOSTIC,
                PendingQuestion(question_id=f"DIAGNOSTIC:{diagnostic.playbook_id}:{pending.fact_key}",
                    fact_key=pending.fact_key, target="diagnostic", answer_type="boolean"),
                diagnostic_fact=pending.fact_key,
            )
        if (feedback is None or not feedback.understood) and not technical_context_changed:
            return ask_question(conversation, diagnostic, SupportDecisionType.ASK_FEEDBACK,
                PendingQuestion(question_id=f"FEEDBACK:DETAILS:{resolution.attempts[-1].step.source_id}", target="feedback"),
                reply="Napisz proszę, co udało Ci się zrobić i czy problem nadal występuje.",
            )
        if feedback is not None and feedback.clarification_requested:
            return ask_question(conversation, diagnostic, SupportDecisionType.CLARIFY_STEP,
                PendingQuestion(question_id=f"CLARIFY:{resolution.attempts[-1].step.source_id}", target="feedback"))
        if (
            feedback is not None
            and feedback.problem_resolved is None
            and feedback.step_completed is not False
            and not technical_context_changed
        ):
            return ask_question(conversation, diagnostic, SupportDecisionType.ASK_FEEDBACK,
                PendingQuestion(question_id=f"FEEDBACK:{resolution.attempts[-1].step.source_id}",
                    target="feedback", answer_type="boolean", action_id=resolution.attempts[-1].step.source_id),
                reply="Czy problem został rozwiązany?",
            )

                                                                           
    if not incident.category or not incident.summary:
        return ask_question(conversation, diagnostic, SupportDecisionType.ASK_TRIAGE,
            PendingQuestion(question_id="TRIAGE:problem_description", target="incident"),
            triage_need=TriageNeed.PROBLEM_DESCRIPTION,
        )

    if diagnostic.playbook_id is not None:
        step = get_next_playbook_action(diagnostic, resolution)
        if step is not None:
            return SupportDecision(
                SupportDecisionType.PLAYBOOK_ACTION, diagnostic, resolution_step=step,
            )
        fact = get_next_diagnostic_fact(diagnostic)
        if fact is not None:
            return ask_question(conversation, diagnostic, SupportDecisionType.ASK_DIAGNOSTIC,
                PendingQuestion(question_id=f"DIAGNOSTIC:{diagnostic.playbook_id}:{fact}",
                    fact_key=fact, target="diagnostic",
                    answer_type="boolean" if fact in playbook.boolean_facts else "text"),
                diagnostic_fact=fact,
            )

    handoff = get_playbook_escalation(diagnostic, resolution, exhausted=True)
    if handoff:
        return SupportDecision(
            SupportDecisionType.ESCALATE, diagnostic,
            escalation_reason=handoff.reason, reply=handoff.reply, escalation_policy=handoff,
        )

    profile = select_profile(incident)
    kb_allowed = (playbook is None or playbook.allow_knowledge) and (profile is None or profile.allow_knowledge)
    if not resolution.knowledge_exhausted and kb_allowed:
        return SupportDecision(SupportDecisionType.SEARCH_KNOWLEDGE, diagnostic)

    need = get_next_triage_need(incident)
    if need is not None:
        canonical = TRIAGE_QUESTIONS.get(need)
        return ask_question(conversation, diagnostic, SupportDecisionType.ASK_TRIAGE,
            PendingQuestion(question_id=f"TRIAGE:{need.value}", target="incident",
                fact_key=canonical[0] if canonical else None,
                answer_type="boolean" if canonical and canonical[0] in TRIAGE_BOOLEAN_FIELDS else "text"), triage_need=need,
        )
    return SupportDecision(
        SupportDecisionType.ESCALATE, diagnostic,
        escalation_reason="Approved playbook actions and trusted L1 knowledge were exhausted.",
        reply=(
            "Wyczerpałem bezpieczne możliwości rozwiązania problemu. "
            "Zgłoszenie zostało przekazane do IT wraz z zebranym kontekstem."
        ),
    )
