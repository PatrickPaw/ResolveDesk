import json
import re

import httpx
import ollama
from pydantic import ValidationError

from app.ai.prompts import (
    MESSAGE_ANALYSIS_SYSTEM_PROMPT,
    DIAGNOSTIC_ANALYSIS_SYSTEM_PROMPT,
    IT_EXPLANATION_SYSTEM_PROMPT,
    SECURITY_ASSESSMENT_SYSTEM_PROMPT,
    RESOLUTION_SYSTEM_PROMPT,
)
from app.ai.provider import (
    AIProviderResponseError,
    AIProviderUnavailableError,
    provider_operation,
    remaining_timeout,
)
from app.core.config import settings
from app.models.conversation import (
    DiagnosticAnalysis,
    DiagnosticState,
    MessageAnalysis,
    MessageContext,
    SecurityAssessment,
)
from app.models.incident import IncidentState
from app.models.knowledge import KnowledgeArticle
from app.models.resolution import (
    ResolutionProposal,
    ResolutionState,
)
from app.services.security import validate_security_assessment


from app.services.catalog import get_catalog


DERIVED_INCIDENT_FIELDS = ("summary", "category", "subcategory", "issue_family")


def exact_message_span(message: str, quote: str) -> str | None:
    quote = quote.strip()
    if not quote:
        return None
    match = re.search(re.escape(quote), message, flags=re.IGNORECASE)
    return match.group(0) if match else None


class OllamaProvider:
    EMBEDDING_DIMENSIONS = 768

    def __init__(self, model: str | None = None, embedding_model: str | None = None,
                 host: str | None = None, think: bool | None = None):
        self.model = model or settings.ollama_model
        self.think = settings.ollama_think if think is None else think
        self.embedding_model = embedding_model or settings.ollama_embedding_model
        self.host = host or settings.ollama_host

    def _client(self):
        return ollama.Client(host=self.host, timeout=remaining_timeout(settings.ai_call_timeout))

    def _chat(self, prompt, payload, *, schema=None, think=None, response_format=None):
        kwargs = dict(model=self.model, think=self.think if think is None else think,
            messages=[{'role': 'system', 'content': prompt},
                      {'role': 'user', 'content': payload if isinstance(payload, str)
                       else json.dumps(payload, ensure_ascii=False)}],
            options={'temperature': 0 if schema else 0.2})
        if schema:
            kwargs['format'] = response_format or schema.model_json_schema()
            if kwargs['think'] is False:
                kwargs['options']['num_predict'] = 800
        try:
            with self._client() as client:
                return client.chat(**kwargs).message.content
        except (httpx.HTTPError, ollama.ResponseError, OSError) as exc:
            raise AIProviderUnavailableError('AI operation is temporarily unavailable.') from exc

    def _structured(self, schema, prompt, payload, *, think=None, validate=None, response_format=None):
        last_error = None
        for _ in range(2):
            content = self._chat(prompt, payload, schema=schema, think=think, response_format=response_format)
            try:
                result = schema.model_validate_json(content)
                if validate:
                    validate(result)
                return result
            except (ValidationError, ValueError, TypeError, AIProviderResponseError) as exc:
                last_error = exc
                prompt += "\nThe previous result failed validation. Include every required field using the specified types and allowed values. Keep related fields consistent; use exact current-message quotes when evidence is required. Do not infer missing facts."
        raise AIProviderResponseError('AI returned an invalid structured response.') from last_error

    def _text(self, prompt, payload):
        result = self._chat(prompt, payload)
        if not isinstance(result, str) or not result.strip():
            raise AIProviderResponseError('AI returned an empty text response.')
        return result.strip()

    @provider_operation
    def analyze_message(self, message: str, context: MessageContext) -> MessageAnalysis:
        validation_attempt = 0

        def validate(result):
            nonlocal validation_attempt
            validation_attempt += 1
            allowed_incident_fields = set(type(result.incident).model_fields)
            valid_evidence = {}
            for key, quote in result.incident_evidence.items():
                if key not in allowed_incident_fields or not isinstance(quote, str):
                    continue
                span = exact_message_span(message, quote)
                if span and getattr(result.incident, key, None) is not None:
                    valid_evidence[key] = span

            summary = result.incident.summary
            summary_span = exact_message_span(message, summary) if summary else None
            if summary_span:
                valid_evidence["summary"] = summary_span

            anchor = next(
                (valid_evidence[key] for key in DERIVED_INCIDENT_FIELDS if key in valid_evidence),
                None,
            )
            if anchor:
                if summary and "summary" not in valid_evidence:
                    result.incident = result.incident.model_copy(update={"summary": message.strip()})
                for key in DERIVED_INCIDENT_FIELDS:
                    if getattr(result.incident, key, None) is not None:
                        valid_evidence.setdefault(key, anchor)

            incident_values = result.incident.model_dump(mode="python", exclude_none=True)
            unsupported = set(incident_values) - set(valid_evidence)
            implicit_defaults = {
                key for key in unsupported
                if incident_values[key] is False or incident_values[key] in ([], {}, "")
            }
            if implicit_defaults:
                result.incident = result.incident.model_copy(
                    update={field: None for field in implicit_defaults}
                )
                unsupported -= implicit_defaults
            if unsupported and validation_attempt == 1:
                raise ValueError(
                    "Every non-null incident field requires an exact quote from "
                    "the current user message; evidence values cannot be labels."
                )
            if unsupported:
                result.incident = result.incident.model_copy(
                    update={field: None for field in unsupported}
                )
            result.incident_evidence = valid_evidence
            result.feedback = result.scoped_feedback()
            if result.outcome_scope != "ORIGINAL_PROBLEM":
                result.resolution_evidence = None
            if result.resolution_evidence and result.feedback.problem_resolved is not True:
                raise ValueError("Resolution evidence and outcome disagree.")
            if result.feedback.problem_resolved is True:
                evidence = (result.resolution_evidence or "").strip()
                if not evidence or evidence not in message:
                    raise ValueError("Resolution requires evidence from this message.")
            if context.current_step is None:
                result.feedback.step_completed = None
        schema = MessageAnalysis.model_json_schema()
        schema["required"].extend(["outcome_scope", "incident_evidence"])
        schema["$defs"]["ResolutionFeedback"]["required"] = ["understood", "clarification_requested", "step_completed", "problem_resolved"]
        schema["$defs"]["IncidentAnalysis"]["required"] = [
            "category", "subcategory", "summary", "issue_family",
            "password_forgotten", "physical_hazard",
        ]
        schema["$defs"]["IncidentAnalysis"]["properties"]["service_profile"] = {"type": "null"}
        return self._structured(MessageAnalysis, MESSAGE_ANALYSIS_SYSTEM_PROMPT, {
            "conversation_context": context.model_dump(mode="json", exclude_none=True),
            "user_message": message,
        }, think=self.think, validate=validate, response_format=schema)


    @provider_operation
    def assess_security_event(self, message: str, context: MessageContext) -> SecurityAssessment:
        return self._structured(SecurityAssessment, SECURITY_ASSESSMENT_SYSTEM_PROMPT, {
            'conversation_context': context.model_dump(mode='json'), 'user_message': message},
            validate=lambda result: validate_security_assessment(result, message))

    @provider_operation
    def generate_it_explanation(self, message: str) -> str:
        return self._text(IT_EXPLANATION_SYSTEM_PROMPT, message)


    @provider_operation
    def analyze_diagnostic_response(self, message: str, incident: IncidentState,
            diagnostic: DiagnosticState, playbook_id: str, allowed_facts: dict[str, str],
            last_question: str | None = None) -> DiagnosticAnalysis:
        def validate(result):
            if (set(result.facts) | set(result.uncertain_facts)) - set(allowed_facts):
                raise ValueError('Unknown diagnostic facts.')
            result.facts = {key: value for key, value in result.facts.items()
                if result.evidence.get(key, "").strip()
                and result.evidence[key] in message}
        response_format = DiagnosticAnalysis.model_json_schema()
        response_format['required'].extend(['facts', 'evidence'])
        playbook = next((p for p in get_catalog() if p.playbook_id == playbook_id), None)
        properties = {}
        for key in allowed_facts:
            spec = playbook.fact_definitions.get(key) if playbook else None
            value_schema = {'type': spec.value_type if spec else 'string'}
            if spec and spec.allowed_values:
                value_schema['enum'] = list(spec.allowed_values)
            properties[key] = {'description': allowed_facts[key],
                               'anyOf': [value_schema, {'type': 'null'}]}
        handoff_facts = sorted({key for rule in playbook.rules if rule.escalation
            for condition in rule.conditions for key in condition.keys}) if playbook else []
        response_format['properties']['facts'] = {'type': 'object', 'properties': properties,
            'required': handoff_facts, 'additionalProperties': False}
        response_format['properties']['uncertain_facts']['items'] = {'type': 'string', 'enum': list(allowed_facts)}
        return self._structured(DiagnosticAnalysis, DIAGNOSTIC_ANALYSIS_SYSTEM_PROMPT, {
            'incident': incident.model_dump(mode='json'),
            'diagnostic_state': diagnostic.model_dump(mode='json'),
            'playbook_id': playbook_id, 'allowed_facts': allowed_facts,
            'last_question': last_question, 'user_message': message},
            think=bool(self.think and playbook and playbook.extraction_reasoning),
            validate=validate, response_format=response_format)


    @provider_operation
    def generate_resolution_step(self, incident: IncidentState, knowledge: list[KnowledgeArticle],
                                 resolution: ResolutionState) -> ResolutionProposal:
        if not knowledge:
            return ResolutionProposal(applicable=False)
        sources = {article.article_id for article in knowledge}
        def validate(proposal):
            if proposal.applicable and (proposal.step is None or proposal.step.source_id not in sources):
                raise ValueError('Applicable resolution requires an approved source.')
        return self._structured(ResolutionProposal, RESOLUTION_SYSTEM_PROMPT, {
            'incident': incident.model_dump(mode='json'),
            'trusted_knowledge': [article.model_dump(mode='json') for article in knowledge],
            'resolution_state': resolution.model_dump(mode='json')}, validate=validate)


    def embed_query(
        self,
        text: str,
    ) -> list[float]:
        return self._embed(
            f"search_query: {text}"
        )

    def embed_document(
        self,
        text: str,
    ) -> list[float]:
        return self._embed(
            f"search_document: {text}"
        )

    @provider_operation
    def _embed(
        self,
        text: str,
    ) -> list[float]:
        try:
            with self._client() as client:
                response = client.embed(model=self.embedding_model, input=text)
        except (
            httpx.HTTPError,
            ollama.ResponseError,
            OSError,
        ) as exc:
            raise AIProviderUnavailableError(
                "Embedding model is unavailable."
            ) from exc

        if not response.embeddings:
            raise AIProviderResponseError(
                "Embedding model returned no embedding."
            )

        embedding = list(
            response.embeddings[0]
        )

        if len(embedding) != self.EMBEDDING_DIMENSIONS:
            raise AIProviderResponseError(
                "Embedding has invalid dimensions."
            )

        return embedding
