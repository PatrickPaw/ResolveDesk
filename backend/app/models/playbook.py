from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.conversation import DiagnosticValue
from app.models.incident import Category


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FactDefinition(CatalogModel):
    description: str
    value_type: Literal["boolean", "string", "number"] = "string"
    allowed_values: tuple[str, ...] = ()
    answer_aliases: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_answers(self):
        if any(not self.accepts(value) for value in self.answer_aliases.values()):
            raise ValueError("Invalid typed answer alias")
        return self

    def accepts(self, value: DiagnosticValue) -> bool:
        if value is None:
            return True
        if self.value_type == "boolean":
            return type(value) is bool
        if self.value_type == "number":
            return type(value) in (int, float)
        return isinstance(value, str) and (
            not self.allowed_values or value in self.allowed_values
        )


class Condition(CatalogModel):
    keys: tuple[str, ...]
    values: tuple[DiagnosticValue, ...]
    contains: bool = False


class EscalationPolicy(CatalogModel):
    reason: str
    reply: str
    reason_code: str = "L1_HANDOFF"
    ticket_kind: Literal["INCIDENT", "SERVICE_REQUEST", "ACCESS_REQUEST", "SECURITY"] = "INCIDENT"
    queue: str = "IT_SUPPORT"
    safety_stop: bool = False


class PlaybookAction(CatalogModel):
    action_id: str
    instruction: str
    failure_escalation: EscalationPolicy | None = None
    blocked_escalation: EscalationPolicy | None = None
    skip_conditions: tuple[Condition, ...] = ()
    audience: Literal["EMPLOYEE"] = "EMPLOYEE"
    scope: Literal["OWN_DEVICE", "READ_ONLY"] = "OWN_DEVICE"
    result_fact: str | None = None
    asks_resolution: bool = False


class PlaybookRule(CatalogModel):
    rule_id: str
    conditions: tuple[Condition, ...]
    required_facts: tuple[str, ...] = ()
    actions: tuple[PlaybookAction, ...] = ()
    ask_missing_facts: bool = True
    escalation: EscalationPolicy | None = None
    exhausted_escalation: EscalationPolicy | None = None


class Playbook(CatalogModel):
    playbook_id: str
    version: str = "1"
    categories: tuple[Category, ...]
    aliases: tuple[str, ...]
    fact_definitions: dict[str, FactDefinition]
    fallback_facts: tuple[str, ...]
    rules: tuple[PlaybookRule, ...]
    fact_conditions: dict[str, tuple[Condition, ...]] = Field(default_factory=dict)
    questions: dict[str, str] = Field(default_factory=dict)
    clarification_questions: dict[str, str] = Field(default_factory=dict)
    boolean_facts: tuple[str, ...] = ()
    allow_knowledge: bool = True
    extraction_reasoning: bool = False
    resolution_goal: str = "Użytkownik może ponownie wykonać pierwotną czynność na swoim urządzeniu, bez zgłaszanego nadal błędu."
    unresolved_conditions: tuple[Condition, ...] = ()

    @property
    def facts(self) -> dict[str, str]:
        return {key: spec.description for key, spec in self.fact_definitions.items()}

    @model_validator(mode="after")
    def validate_references(self):
        facts = self.fact_definitions
        referenced = set(self.fallback_facts) | set(self.questions) | set(self.clarification_questions) | set(self.boolean_facts) | set(self.fact_conditions)
        conditions = [*self.unresolved_conditions, *(c for group in self.fact_conditions.values() for c in group)]
        rule_ids = set()
        for rule in self.rules:
            if rule.rule_id in rule_ids:
                raise ValueError(f"Duplicate rule: {rule.rule_id}")
            rule_ids.add(rule.rule_id)
            referenced.update(rule.required_facts)
            conditions.extend(rule.conditions)
            for action in rule.actions:
                conditions.extend(action.skip_conditions)
                if action.result_fact:
                    referenced.add(action.result_fact)
                    if action.asks_resolution or facts.get(action.result_fact, FactDefinition(description="")).value_type != "boolean":
                        raise ValueError("Action result must bind to one boolean fact")
        for condition in conditions:
            if not condition.keys or not condition.values:
                raise ValueError("Empty condition")
            referenced.update(condition.keys)
            for key in condition.keys:
                if key in facts and any(not facts[key].accepts(value) for value in condition.values):
                    raise ValueError(f"Invalid condition value for {key}")
        if referenced - set(facts):
            raise ValueError(f"Unknown fact references: {sorted(referenced - set(facts))}")
        asked = set(self.fallback_facts)
        for rule in self.rules:
            if rule.ask_missing_facts:
                asked.update(rule.required_facts)
                asked.update(key for condition in rule.conditions for key in condition.keys)
        if asked - set(self.questions):
            raise ValueError(f"Missing approved questions: {sorted(asked - set(self.questions))}")
        if any(facts[key].value_type != "boolean" for key in self.boolean_facts):
            raise ValueError("Boolean answer binding requires a boolean fact")
                                                                             
        def visit(key, path):
            if key in path:
                raise ValueError(f"Cyclic fact prerequisite: {key}")
            for condition in self.fact_conditions.get(key, ()):
                for dependency in condition.keys:
                    visit(dependency, {*path, key})
        for key in self.fact_conditions:
            visit(key, set())
        return self


class ServiceProfile(CatalogModel):
    profile_id: str
    label: str
    aliases: tuple[str, ...]
    playbook_id: str
    family_overrides: dict[str, str] = Field(default_factory=dict)
    queue: str = "IT_SUPPORT"
    allow_knowledge: bool = False


class CatalogPolicy(CatalogModel):
    family_playbooks: dict[str, str]
    profiles: tuple[ServiceProfile, ...]
