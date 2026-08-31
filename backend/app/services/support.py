import logging

from app.ai.provider import AIProvider, AIProviderResponseError, turn_budget
from app.core.config import settings
from app.db.conversation_repository import PostgreSQLConversationRepository
from app.db.knowledge_repository import PostgreSQLKnowledgeRepository
from app.db.resolved_incident_repository import PostgreSQLResolvedIncidentRepository
from app.db.ticket_repository import PostgreSQLTicketRepository
from app.models.chat import ChatRequest, ChatResponse
from app.models.conversation import (
    ConversationStage, ConversationState, DiagnosticAnalysis, MessageClassification, MessageContext,
    MessageIntent, SecurityEventType, FactEvidence, MessageAnalysis, PendingQuestion,
)
from app.models.explainability import (
    DecisionTrace, ExplainabilityTrace, ExtractedFactTrace,
    KnowledgeCandidateTrace, ValidationTrace,
)
from app.models.incident import Category, IncidentAnalysis, IncidentState
from app.models.knowledge import KnowledgeArticle
from app.models.resolution import ResolutionFeedback, ResolutionOutcome
from app.models.resolved_incident import ResolvedIncident
from app.services.conversation import (
    SupportDecisionType, decide_next_support_action, merge_incident_analysis,
    TRIAGE_QUESTIONS, TECHNICAL_HINT_ACKNOWLEDGEMENT, parse_short_answer, short_triage_answer,
    bound_short_answer,
)
from app.services.knowledge import build_knowledge_query_text, retrieve_knowledge
from app.services.playbook import get_playbook, process_diagnostic_message, start_diagnosis, has_current_blocker
from app.services.priority import determine_impact, determine_priority, determine_urgency
from app.services.resolution import (
    get_next_resolution_step, start_resolution_step, apply_resolution_feedback,
)
from app.services.security import (
    REDACTED_MESSAGE, contains_explicit_sensitive_data, verify_security_signal,
)
from app.services.ticket import create_escalation_ticket
from app.services.password_reset_demo import demo_available

logger = logging.getLogger("resolvedesk.support")


class ConversationNotFoundError(ValueError):
    pass


class ConversationClosedError(ValueError):
    pass


def assess_incident(incident: IncidentState) -> IncidentState:
    return incident.model_copy(update={
        "impact": determine_impact(incident),
        "urgency": determine_urgency(incident),
        "priority": determine_priority(incident),
    })


def build_resolution_summary(conversation: ConversationState) -> str:
    lines = ["Diagnostic context:"]
    lines.extend(f"- {key}: {value}" for key, value in sorted(conversation.diagnostic.facts.items()))
    lines.append("Resolution steps:")
    for index, attempt in enumerate(conversation.resolution.attempts, 1):
        lines.append(f"{index}. {attempt.step.instruction}")
        lines.append(f"Source: {attempt.step.source_id}; completed={attempt.step_completed}; resolved={attempt.problem_resolved}")
    if conversation.resolution.user_resolution:
        lines.append("User-reported resolution (not a verified knowledge article):")
        lines.append(conversation.resolution.user_resolution)
    return "\n".join(lines)


class SupportService:
    def __init__(
        self,
        ai: AIProvider,
        conversations: PostgreSQLConversationRepository,
        knowledge: PostgreSQLKnowledgeRepository,
        tickets: PostgreSQLTicketRepository,
        resolved_incidents: PostgreSQLResolvedIncidentRepository,
        explain: bool = False,
    ):
        self.ai = ai
        self.conversations = conversations
        self.knowledge = knowledge
        self.tickets = tickets
        self.resolved_incidents = resolved_incidents
        self.explain = explain
        self._trace: ExplainabilityTrace | None = None

    def _record_interpretation(
        self,
        message: str,
        classification: MessageClassification,
        analysis: MessageAnalysis | None,
        *,
        sensitive: bool,
        literal: bool,
    ) -> None:
        if not self._trace:
            return
        self._trace.input_text = REDACTED_MESSAGE if sensitive else message
        self._trace.input_redacted = sensitive
        self._trace.interpretation_source = (
            "SECURITY_RULE" if sensitive else "LITERAL" if literal else "AI"
        )
        self._trace.intent = classification.intent.value
        if analysis is None:
            self._trace.validations.append(ValidationTrace(
                check="AI_STRUCTURED_OUTPUT",
                passed=True,
                detail="AI was intentionally bypassed for a literal answer or security rule.",
            ))
            return
        patch = analysis.incident.model_dump(mode="json", exclude_none=True)
        self._trace.incident_patch = patch
        for key, value in patch.items():
            quote = analysis.incident_evidence.get(key)
            self._trace.extracted_facts.append(ExtractedFactTrace(
                key=f"incident.{key}",
                value=value,
                source="AI",
                evidence=quote,
                evidence_valid=bool(quote and quote in message),
            ))
        self._trace.validations.append(ValidationTrace(
            check="AI_STRUCTURED_OUTPUT",
            passed=True,
            detail="Pydantic accepted the structured message analysis.",
        ))
        quoted = [
            item for item in self._trace.extracted_facts
            if item.key.startswith("incident.") and item.evidence is not None
        ]
        self._trace.validations.append(ValidationTrace(
            check="CURRENT_MESSAGE_QUOTES",
            passed=all(item.evidence_valid for item in quoted),
            detail=f"{sum(item.evidence_valid for item in quoted)}/{len(quoted)} supplied incident quotes match the current message.",
        ))

    def _record_diagnostic_analysis(
        self, message: str, analysis: DiagnosticAnalysis,
    ) -> None:
        if not self._trace:
            return
        for key, value in analysis.facts.items():
            quote = analysis.evidence.get(key)
            self._trace.extracted_facts.append(ExtractedFactTrace(
                key=f"diagnostic.{key}",
                value=value,
                source="AI",
                evidence=quote,
                evidence_valid=bool(quote and quote in message),
            ))
        self._trace.validations.append(ValidationTrace(
            check="CATALOG_FACT_ALLOWLIST",
            passed=True,
            detail="All accepted diagnostic fact keys and values match the selected playbook schema.",
        ))

    def _record_literal_fact(self, key: str, value, message: str) -> None:
        if not self._trace:
            return
        self._trace.extracted_facts.append(ExtractedFactTrace(
            key=key, value=value, source="LITERAL",
            evidence=message, evidence_valid=True,
        ))

    def _record_decision(self, conversation: ConversationState, decision) -> None:
        if not self._trace:
            return
        playbook = get_playbook(conversation.diagnostic.playbook_id)
        self._trace.playbook_id = conversation.diagnostic.playbook_id
        self._trace.playbook_version = playbook.version if playbook else None
        kind = decision.decision_type
        source = "SECURITY_RULE" if conversation.security_emergency else "PYTHON_RULE"
        reason = decision.escalation_reason
        if not reason and decision.diagnostic_fact:
            reason = f"Missing approved diagnostic fact: {decision.diagnostic_fact}."
        if not reason and decision.resolution_step:
            reason = f"Approved catalog action selected: {decision.resolution_step.source_id}."
        if not reason and decision.pending_question:
            reason = f"Deterministic engine selected question: {decision.pending_question.question_id}."
        if not reason:
            reason = "Deterministic workflow state and safety policy selected this transition."
        self._trace.decisions.append(DecisionTrace(
            decision_type=kind.value,
            source=source,
            reason=reason,
            question_id=decision.pending_question.question_id if decision.pending_question else None,
            action_source_id=decision.resolution_step.source_id if decision.resolution_step else None,
        ))
        if kind == SupportDecisionType.ESCALATE:
            self._trace.escalation_reason = decision.escalation_reason

    def handle(self, request: ChatRequest) -> ChatResponse:
        with turn_budget(settings.ai_turn_timeout):
            return self._handle(request)

    def _handle(self, request: ChatRequest) -> ChatResponse:
        self._trace = (
            ExplainabilityTrace(input_text=request.message)
            if self.explain else None
        )
        if request.conversation_id is None:
            conversation = self.conversations.create()
        else:
                                                                              
            conversation = self.conversations.get(request.conversation_id, for_update=True)
            if conversation is None:
                raise ConversationNotFoundError("Conversation not found.")
        if conversation.stage in {ConversationStage.RESOLVED, ConversationStage.ESCALATED}:
            raise ConversationClosedError("Conversation is already closed.")

        sensitive = contains_explicit_sensitive_data(request.message)
        short_answer = bound_short_answer(conversation, request.message)
        security_event = None
        analysis = None
        if sensitive:
            security_event = SecurityEventType.CREDENTIAL_EXPOSURE
            classification = MessageClassification(
                intent=MessageIntent.SECURITY_INCIDENT,
                security_emergency=True, sensitive_data_detected=True,
            )
        elif short_answer:
                                                                                         
            classification = MessageClassification(intent=MessageIntent.INCIDENT)
        else:
            context = MessageContext.from_conversation(conversation)
            playbook = get_playbook(conversation.diagnostic.playbook_id)
            context.resolution_goal = playbook.resolution_goal if playbook else None
            analysis = self.ai.analyze_message(request.message, context)
            classification = analysis.classification
            assessment = verify_security_signal(self.ai, request.message, context, classification)
                                                                             
                                                                             
            sensitive = classification.sensitive_data_detected or (
                assessment is not None and assessment.contains_secret
            )
            if assessment is not None:
                security_event = assessment.event_type
            else:
                classification = MessageClassification(
                    intent=(
                        MessageIntent.INCIDENT
                        if classification.intent == MessageIntent.SECURITY_INCIDENT
                        else classification.intent
                    ),
                )

        self._record_interpretation(
            request.message,
            classification,
            analysis,
            sensitive=sensitive,
            literal=bool(short_answer),
        )

        conversation.diagnostic.current_message_id = self.conversations.add_message(
            conversation.conversation_id, "USER",
            REDACTED_MESSAGE if sensitive else request.message,
        )
        if security_event is not None:
            conversation.security_emergency = True
            conversation.incident = assess_incident(conversation.incident.model_copy(update={
                "category": Category.SECURITY,
                "subcategory": security_event.value,
                "summary": (
                    "Ujawnienie danych uwierzytelniających."
                    if security_event == SecurityEventType.CREDENTIAL_EXPOSURE
                    else "Zgłoszono potencjalny incydent bezpieczeństwa."
                ),
                "error_message": None,
                "resolved": False,
            }))
                                                                                       
            return self.execute(conversation, request.message, classification)

        if sensitive:
                                                                               
                                                                                
            return self.execute(conversation, REDACTED_MESSAGE, classification, input_withheld=True)

        if analysis and analysis.incident.physical_hazard is True:
            conversation.incident = assess_incident(merge_incident_analysis(conversation.incident, analysis.incident))
            return self.execute(conversation, request.message, classification)

        feedback = analysis.scoped_feedback() if analysis else None
        previous_context = self.technical_context(conversation)
        previous_incident_context = self.incident_technical_context(conversation)
        if conversation.stage == ConversationStage.RESOLUTION and conversation.resolution.attempts:
            if short_answer and short_answer[0].target == "feedback":
                feedback = ResolutionFeedback(understood=True, problem_resolved=short_answer[1])
                conversation.resolution = apply_resolution_feedback(conversation.resolution, feedback, request.message)
            elif feedback is not None:
                conversation.resolution = apply_resolution_feedback(conversation.resolution, feedback, request.message)
                                                                                  
                                                                                    
                                                                                    
            self.update_state(conversation, request.message, analysis)
        elif not (
            conversation.incident.category is None
            and conversation.incident.summary is None
            and classification.intent in {MessageIntent.OFF_TOPIC, MessageIntent.IT_EXPLANATION}
        ):
            self.update_state(conversation, request.message, analysis)

        if feedback and feedback.problem_resolved is True and has_current_blocker(conversation.diagnostic):
                                                                              
            feedback = feedback.model_copy(update={"problem_resolved": False})
            conversation.resolution.outcome = ResolutionOutcome.CONTINUE
            if conversation.stage == ConversationStage.RESOLUTION and conversation.resolution.attempts:
                conversation.resolution = apply_resolution_feedback(conversation.resolution, feedback, request.message)

                                                                                
                                                                                   
        if feedback and feedback.understood and feedback.problem_resolved is True and not feedback.clarification_requested:
            if analysis is not None:
                evidence = (analysis.resolution_evidence or "").strip()
                if not evidence or evidence not in request.message:
                    raise AIProviderResponseError("Resolution requires current-message evidence.")
            if conversation.incident.category and conversation.incident.summary:
                conversation.resolution.outcome = ResolutionOutcome.RESOLVED
                conversation.resolution.user_resolution = request.message

        updated_context = self.technical_context(conversation)
        context_changed = updated_context != previous_context
        if feedback is not None and feedback.step_completed is True and feedback.problem_resolved is None:
                                                                             
                                                                              
                                                                              
            context_changed = self.incident_technical_context(conversation) != previous_incident_context
        return self.execute(
            conversation, request.message, classification, feedback,
            technical_context_changed=context_changed,
        )

    def update_state(self, conversation: ConversationState, message: str, understanding: MessageAnalysis | None) -> None:
        previous_context = self.technical_context(conversation)
        answer = bound_short_answer(conversation, message)
        if answer:
            question, value = answer
            if question.target == "incident":
                conversation.incident = assess_incident(merge_incident_analysis(
                    conversation.incident, IncidentAnalysis(**{question.fact_key: value})))
                self._record_literal_fact(f"incident.{question.fact_key}", value, message)
            elif question.target == "diagnostic":
                conversation.diagnostic.facts[question.fact_key] = value
                conversation.diagnostic.fact_evidence[question.fact_key] = FactEvidence(
                    source_message_id=conversation.diagnostic.current_message_id)
                conversation.resolution.knowledge_exhausted = False
                self._record_literal_fact(f"diagnostic.{question.fact_key}", value, message)
            conversation.diagnostic.pending_fact = None
            conversation.diagnostic.pending_question = None
            return
        if conversation.stage == ConversationStage.ACTIVE:
            answer = short_triage_answer(message, conversation.last_question)
            if answer is not None:
                conversation.incident = assess_incident(merge_incident_analysis(conversation.incident, answer))
                for key, value in answer.model_dump(exclude_none=True).items():
                    self._record_literal_fact(f"incident.{key}", value, message)
                conversation.diagnostic.pending_fact = None
                return
            playbook = get_playbook(conversation.diagnostic.playbook_id)
            key = conversation.diagnostic.pending_fact
            value = parse_short_answer(message)
            if (
                value is not None and playbook and key in playbook.boolean_facts
                and conversation.last_question == playbook.questions.get(key)
            ):
                conversation.diagnostic.facts[key] = value
                self._record_literal_fact(f"diagnostic.{key}", value, message)
                conversation.diagnostic.pending_fact = None
                conversation.resolution.knowledge_exhausted = False
                return
        if understanding is None:
            raise ValueError("A nonliteral answer requires message interpretation.")
        analysis = understanding.incident
        conversation.incident = assess_incident(merge_incident_analysis(conversation.incident, analysis))
        conversation.diagnostic = start_diagnosis(conversation.incident, conversation.diagnostic)
        playbook = get_playbook(conversation.diagnostic.playbook_id)
        if playbook and playbook.facts and analysis.password_forgotten is not True:
            shared_updates = {
                key: value for key, value in analysis.model_dump(exclude_none=True).items()
                if key in playbook.facts
            }
            conversation.diagnostic.facts = {
                **conversation.diagnostic.facts, **shared_updates,
            }
            conversation.diagnostic, diagnostic_analysis = process_diagnostic_message(
                self.ai, message, conversation.incident, conversation.diagnostic,
                last_question=conversation.last_question,
            )
            self._record_diagnostic_analysis(message, diagnostic_analysis)
            if diagnostic_analysis.understood and "error_message" in diagnostic_analysis.facts:
                value = diagnostic_analysis.facts["error_message"]
                if value is None or isinstance(value, str):
                    conversation.incident.error_message = value
                                                                             
                                                                                
        if self.technical_context(conversation) != previous_context:
            conversation.resolution.knowledge_exhausted = False

    @staticmethod
    def incident_technical_context(conversation: ConversationState) -> tuple:
        incident = conversation.incident
        return (
            incident.category, incident.subcategory, incident.error_message,
            incident.password_forgotten,
            tuple(incident.technical_observations),
        )

    @classmethod
    def technical_context(cls, conversation: ConversationState) -> tuple:
        return (
            *cls.incident_technical_context(conversation),
            conversation.diagnostic.playbook_id,
            tuple(sorted(conversation.diagnostic.facts.items())),
        )

    def retrieve_knowledge(self, conversation: ConversationState) -> list[KnowledgeArticle]:
        query = build_knowledge_query_text(conversation.incident, conversation.diagnostic)
        return retrieve_knowledge(self.knowledge, conversation.incident, self.ai.embed_query(query))

    def reply(
        self, conversation: ConversationState, text: str, ticket_id: str | None = None,
    ) -> ChatResponse:
        self.conversations.save(conversation)
        self.conversations.add_message(conversation.conversation_id, "ASSISTANT", text)
        return ChatResponse(
            conversation_id=conversation.conversation_id, stage=conversation.stage,
            incident=conversation.incident, reply=text, ticket_id=ticket_id,
            password_reset_demo_available=demo_available(conversation),
            explainability=self._trace,
        )

    def execute(
        self, conversation: ConversationState, message: str,
        classification: MessageClassification | None = None,
        feedback: ResolutionFeedback | None = None,
        input_withheld: bool = False,
        technical_context_changed: bool = False,
    ) -> ChatResponse:
                                                                                      
        rechecked_knowledge = False
        while True:
            decision = decide_next_support_action(
                conversation, classification, feedback, input_withheld=input_withheld,
                technical_context_changed=technical_context_changed,
                password_reset_demo_enabled=settings.password_reset_demo_enabled,
            )
            conversation.diagnostic = decision.diagnostic
            kind = decision.decision_type
            self._record_decision(conversation, decision)
            logger.info("decision=%s playbook=%s question=%s", kind.value,
                conversation.diagnostic.playbook_id,
                decision.pending_question.question_id if decision.pending_question else None)
            if decision.pending_question:
                question = decision.pending_question
                conversation.diagnostic.pending_question = question
                attempts = conversation.diagnostic.question_attempts
                attempts[question.question_id] = attempts.get(question.question_id, 0) + 1
            elif kind not in {SupportDecisionType.REPLY, SupportDecisionType.EXPLAIN_IT}:
                conversation.diagnostic.pending_question = None

            if kind == SupportDecisionType.DEMO_PASSWORD_RESET:
                conversation.stage = ConversationStage.ACTIVE
                conversation.last_question = None
                conversation.diagnostic.pending_fact = None
                return self.reply(conversation, decision.reply)

            if kind == SupportDecisionType.SEARCH_KNOWLEDGE:
                rechecked_knowledge = True
                knowledge = self.retrieve_knowledge(conversation)
                if self._trace:
                    self._trace.knowledge_candidates = [
                        KnowledgeCandidateTrace(
                            article_id=article.article_id,
                            title=article.title,
                            retrieval_method=article.retrieval_method or "CATEGORY",
                            similarity=article.retrieval_similarity,
                        )
                        for article in knowledge
                    ]
                conversation.resolution, step = get_next_resolution_step(
                    self.ai, conversation.incident, knowledge, conversation.resolution,
                )
                if step is None:
                    if self._trace:
                        self._trace.decisions.append(DecisionTrace(
                            decision_type="RAG_REJECTED_OR_EMPTY",
                            source="RAG",
                            reason="No complete, approved and safe source line was accepted.",
                        ))
                    conversation.stage = ConversationStage.ACTIVE
                    feedback = None
                    continue
                if self._trace:
                    for candidate in self._trace.knowledge_candidates:
                        candidate.selected = candidate.article_id == step.source_id
                    self._trace.decisions.append(DecisionTrace(
                        decision_type="RAG_ACTION",
                        source="RAG",
                        reason="The selected instruction exactly matches a complete line in an approved source.",
                        action_source_id=step.source_id,
                    ))
                conversation.stage = ConversationStage.RESOLUTION
                conversation.last_question = None
                return self.reply(conversation, step.instruction)

            if kind == SupportDecisionType.PLAYBOOK_ACTION:
                step = decision.resolution_step
                if step is None:
                    raise ValueError("Playbook action requires a step.")
                conversation.resolution = start_resolution_step(conversation.resolution, step)
                conversation.stage = ConversationStage.RESOLUTION
                conversation.last_question = None
                playbook = get_playbook(conversation.diagnostic.playbook_id)
                action = next(a for rule in playbook.rules for a in rule.actions if f"PLAYBOOK-{a.action_id}" == step.source_id)
                if action.result_fact or action.asks_resolution:
                    conversation.last_question = step.instruction
                    conversation.diagnostic.pending_question = PendingQuestion(
                        question_id=f"ACTION:{action.action_id}",
                        target="diagnostic" if action.result_fact else "feedback",
                        fact_key=action.result_fact, answer_type="boolean", action_id=step.source_id,
                    )
                    conversation.diagnostic.pending_fact = action.result_fact
                return self.reply(conversation, step.instruction)

            if kind == SupportDecisionType.ASK_TRIAGE:
                if decision.triage_need is None:
                    raise ValueError("Triage decision requires a missing field.")
                canonical = TRIAGE_QUESTIONS.get(decision.triage_need)
                question = canonical[1]
                if technical_context_changed and rechecked_knowledge and conversation.incident.technical_observations:
                    question = TECHNICAL_HINT_ACKNOWLEDGEMENT + question
                conversation.stage = ConversationStage.ACTIVE
                conversation.diagnostic.pending_fact = None
                conversation.last_question = question
                return self.reply(conversation, question)

            if kind == SupportDecisionType.ASK_DIAGNOSTIC:
                playbook = get_playbook(conversation.diagnostic.playbook_id)
                key = decision.diagnostic_fact
                if playbook is None or key not in playbook.facts:
                    raise ValueError("Diagnostic decision requires an allowed fact.")
                repeated = conversation.diagnostic.pending_fact == key
                question = (
                    playbook.clarification_questions.get(key) if repeated else None
                ) or playbook.questions.get(key)
                if question is None:
                    raise ValueError(f"Catalog question missing: {playbook.playbook_id}:{key}")
                conversation.diagnostic.pending_fact = key
                conversation.stage = ConversationStage.ACTIVE
                conversation.last_question = question
                return self.reply(conversation, question)

            if kind == SupportDecisionType.RESOLVED:
                conversation.stage = ConversationStage.RESOLVED
                conversation.last_question = None
                conversation.incident.resolved = True
                                                                                       
                self.resolved_incidents.save(ResolvedIncident(
                    conversation_id=conversation.conversation_id,
                    category=conversation.incident.category,
                    subcategory=conversation.incident.subcategory,
                    summary=conversation.incident.summary,
                    error_message=conversation.incident.error_message,
                    resolution=build_resolution_summary(conversation),
                ))
                return self.reply(conversation, "Problem został rozwiązany. Zapisałem przebieg rozwiązania.")

            if kind == SupportDecisionType.ESCALATE:
                conversation.stage = ConversationStage.ESCALATED
                conversation.last_question = None
                conversation.resolution.outcome = ResolutionOutcome.ESCALATE
                ticket = create_escalation_ticket(conversation, decision.escalation_reason or "L1 exhausted.", decision.escalation_policy)
                self.tickets.save(ticket)
                return self.reply(conversation, decision.reply or "Zgłoszenie przekazane do IT.", ticket.ticket_id)

            if kind == SupportDecisionType.CLARIFY_STEP:
                step = conversation.resolution.attempts[-1].step
                                                                                  
                return self.reply(conversation, f"Zatwierdzony krok to: {step.instruction}\nJeśli nie możesz go wykonać, napisz, co Cię zatrzymuje.")

            if kind == SupportDecisionType.EXPLAIN_IT:
                return self.reply(conversation, self.ai.generate_it_explanation(message))

            if kind in {SupportDecisionType.ASK_FEEDBACK, SupportDecisionType.REPLY}:
                if kind == SupportDecisionType.ASK_FEEDBACK:
                    conversation.last_question = decision.reply
                return self.reply(conversation, decision.reply or "Opisz proszę problem.")

            raise ValueError(f"Unsupported support decision: {kind}")
