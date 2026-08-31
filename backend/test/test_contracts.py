from copy import deepcopy
import json

import httpx
import pytest
from pydantic import ValidationError

from app.ai import provider
from app.ai.ollama_provider import OllamaProvider
from app.ai.provider import AIProviderUnavailableError, AIProviderResponseError
from app.models.conversation import DiagnosticAnalysis, DiagnosticState, MessageContext, MessageAnalysis
from app.models.incident import IncidentState
from app.models.playbook import Playbook
from app.models.resolution import ResolutionState, ResolutionProposal, ResolutionStep
from app.models.knowledge import KnowledgeArticle
from app.services.catalog import CATALOG_ROOT, get_catalog, load_catalog
from app.services.playbook import process_diagnostic_message, select_playbook
from app.services.playbook import has_current_blocker
from app.models.conversation import FactEvidence
from app.services.resolution import get_next_resolution_step
from app.services.security import contains_explicit_sensitive_data
from app.services.password_reset_demo import DemoCodeStore, DemoCodeError


def test_catalog_files_are_required(tmp_path):
    with pytest.raises(FileNotFoundError): load_catalog(tmp_path)


@pytest.mark.parametrize("subject,category,expected", [
    ("PRINTING", "HARDWARE", "PRINTING"),
    ("VPN", "NETWORK", "VPN"),
    ("MONITOR", "HARDWARE", "MONITOR"),
])
def test_known_subject_wins_over_unrelated_model_family(subject, category, expected):
    state=IncidentState(category=category, subcategory=subject, issue_family="PAYMENTS")
    assert select_playbook(state).playbook_id == expected


@pytest.mark.parametrize("playbook", get_catalog(), ids=lambda p:p.playbook_id)
def test_catalog_rejects_missing_question(playbook):
    data=playbook.model_dump()
    if not data["questions"]:
        return                                         
    data["questions"]={}
    with pytest.raises(ValidationError): Playbook.model_validate(data)


@pytest.mark.parametrize("text", ["Moje hasło jest aktualne", "Hasło jest nieaktualne", "Hasło jest wygasłe", "Nie pamiętam hasła", "Nie zostało wykryte"])
def test_ordinary_status_is_not_credential_disclosure(text):
    assert not contains_explicit_sensitive_data(text)


@pytest.mark.parametrize("text", ["Moje hasło to DemoSecret123", "hasło jest DemoSecret123", "kod MFA: 123456", "token=ExampleTokenOnly"])
def test_explicit_secrets_are_detected(text):
    assert contains_explicit_sensitive_data(text)


def test_ai_deadline_is_shared_and_reset(monkeypatch):
    now=[100.0]
    monkeypatch.setattr(provider,"monotonic",lambda:now[0])
    with provider.turn_budget(30):
        assert provider.remaining_timeout(45)==30
        now[0]+=20
        assert provider.remaining_timeout(45)==10
        now[0]+=11
        with pytest.raises(AIProviderUnavailableError): provider.remaining_timeout(45)
    assert provider.remaining_timeout(45)==45


def test_ai_outage_does_not_retry_or_invent_facts(monkeypatch):
    ai=OllamaProvider()
    calls=[]
    def fail(*args,**kwargs):
        calls.append(1)
        raise AIProviderUnavailableError("offline")
    monkeypatch.setattr(ai,"_chat",fail)
    with pytest.raises(AIProviderUnavailableError) as error:
        ai.analyze_message("No signal",MessageContext())
    assert error.value.operation == "analyze_message" and len(calls)==1


def test_derived_incident_facts_share_current_message_evidence(monkeypatch):
    ai = OllamaProvider()
    calls = []
    def unsupported_response(*args, **kwargs):
        calls.append(1)
        return json.dumps({
        "classification": {"intent": "INCIDENT"},
        "incident": {
            "category": "HARDWARE",
            "subcategory": "MONITOR",
            "summary": "Historyczny opis bez dowodu",
            "issue_family": "DEVICE",
        },
        "incident_evidence": {
            "category": "Monitor",
            "subcategory": "historyczny monitor",
            "issue_family": "Monitor",
        },
        "feedback": {"understood": True},
        "outcome_scope": "UNSPECIFIED",
        "resolution_evidence": None,
        })
    monkeypatch.setattr(ai, "_chat", unsupported_response)

    result = ai.analyze_message("Monitor nie działa", MessageContext())

    assert result.incident.category.value == "HARDWARE"
    assert result.incident.issue_family.value == "DEVICE"
    assert result.incident.subcategory == "MONITOR"
    assert result.incident.summary == "Monitor nie działa"
    assert result.incident_evidence == {
        "category": "Monitor",
        "subcategory": "Monitor",
        "summary": "Monitor",
        "issue_family": "Monitor",
    }
    assert len(calls) == 1


def test_short_printer_report_keeps_subject_and_summary(monkeypatch):
    ai = OllamaProvider()
    monkeypatch.setattr(ai, "_chat", lambda *args, **kwargs: json.dumps({
        "classification": {"intent": "INCIDENT"},
        "incident": {
            "category": "HARDWARE",
            "subcategory": "PRINTING",
            "summary": "Nie działa drukarka",
            "issue_family": "PRINTING",
            "physical_hazard": False,
            "password_forgotten": False,
            "technical_observations": [],
        },
        "incident_evidence": {"category": "nie działa drukarka"},
        "feedback": {"understood": True},
        "outcome_scope": "UNSPECIFIED",
        "resolution_evidence": None,
    }))

    result = ai.analyze_message("Nie działa drukarka", MessageContext())

    assert result.incident.category.value == "HARDWARE"
    assert result.incident.subcategory == "PRINTING"
    assert result.incident.issue_family.value == "PRINTING"
    assert result.incident.summary == "Nie działa drukarka"
    assert result.incident.physical_hazard is None
    assert result.incident.password_forgotten is None
    assert result.incident.technical_observations is None
    assert set(result.incident_evidence) == {
        "category", "subcategory", "summary", "issue_family",
    }
    assert set(result.incident_evidence.values()) == {"Nie działa drukarka"}


def test_unknown_diagnostic_fact_is_rejected():
    class BadAI:
        def analyze_diagnostic_response(self, **kwargs):
            return DiagnosticAnalysis(understood=True,facts={"invented_fact":True})
    with pytest.raises(AIProviderResponseError):
        process_diagnostic_message(BadAI(),"test",IncidentState(),DiagnosticState(playbook_id="MONITOR"))


def test_historical_diagnostic_fact_cannot_be_relabelled_as_fresh(monkeypatch):
    ai=OllamaProvider()
    monkeypatch.setattr(ai, "_chat", lambda *args, **kwargs: json.dumps({
        "understood": True, "facts": {"error_message":"No signal", "powered":True},
        "evidence": {"error_message":"No signal", "powered":"Naprawiłem"},
    }))
    result=ai.analyze_diagnostic_response("Naprawiłem", IncidentState(),
        DiagnosticState(playbook_id="MONITOR", facts={"error_message":"No signal"}),
        "MONITOR", {"error_message":"Komunikat", "powered":"Zasilanie"})
    assert result.facts == {"powered":True}


@pytest.mark.parametrize("instruction,accepted", [
    ("Sprawdź kabel własnego monitora.",True),
    ("Zresetuj router.",False),
    ("Wyłącz wspólny switch.",False),
    ("Usuń wszystkie sterowniki.",False),
])
def test_rag_cannot_invent_or_cross_network_boundary(instruction,accepted):
    article=KnowledgeArticle(article_id="KB-1",title="Test",content="Sprawdź kabel własnego monitora.\nZresetuj router.\nWyłącz wspólny switch.",active=True)
    class AI:
        def generate_resolution_step(self,*args):
            return ResolutionProposal(applicable=True,step=ResolutionStep(source_id="KB-1",instruction=instruction))
    _,step=get_next_resolution_step(AI(),IncidentState(),[article],ResolutionState())
    assert (step is not None) is accepted


def test_demo_code_is_single_use_and_bound_to_conversation():
    store=DemoCodeStore()
    value=store.issue("test-conversation")
    assert value["simulated"] and value["delivery"] == "SIMULATED_MAILBOX"
    with pytest.raises(DemoCodeError): store.verify("other",value["challenge_id"],value["demo_code"])
    store.verify("test-conversation",value["challenge_id"],value["demo_code"])
    with pytest.raises(DemoCodeError): store.verify("test-conversation",value["challenge_id"],value["demo_code"])


@pytest.mark.parametrize("scope", ["STEP_ONLY", "OTHER_DEVICE", "UNSPECIFIED"])
@pytest.mark.parametrize("claimed_result", [True, False])
def test_outcome_scope_prevents_false_success_and_failure(scope,claimed_result):
    result=MessageAnalysis(classification={"intent":"INCIDENT"},incident={},
        feedback={"understood":True,"problem_resolved":claimed_result,"step_completed":False},
        outcome_scope=scope,resolution_evidence=None)
    assert result.scoped_feedback().problem_resolved is None
    if scope in {"OTHER_DEVICE","UNSPECIFIED"}:
        assert result.scoped_feedback().step_completed is None


def test_old_error_does_not_override_a_new_resolution():
    diagnostic=DiagnosticState(playbook_id="PRINTING",current_message_id=2,
        facts={"printer_status":"OFFLINE"},fact_evidence={"printer_status":FactEvidence(source_message_id=1)})
    assert not has_current_blocker(diagnostic)
    diagnostic.fact_evidence["printer_status"].source_message_id=2
    assert has_current_blocker(diagnostic)


def test_demo_explainability_shows_ai_facts_rules_and_quotes_without_prompts(chat):
    message = "Monitor pokazuje No signal"
    chat.ai.messages.append(MessageAnalysis(
        classification={"intent": "INCIDENT"},
        incident={
            "category": "HARDWARE", "subcategory": "MONITOR",
            "summary": "Monitor pokazuje No signal", "issue_family": "DEVICE",
        },
        incident_evidence={
            "category": "Monitor", "subcategory": "Monitor",
            "summary": message, "issue_family": "Monitor",
        },
        feedback={"understood": True},
        resolution_evidence=None,
    ))
    chat.ai.diagnostics.append(DiagnosticAnalysis(
        understood=True,
        facts={"error_message": "NO SIGNAL"},
        evidence={"error_message": "No signal"},
    ))
    response = chat.send(message, explain=True)
    trace = response.explainability
    assert trace is not None
    assert trace.input_text == message and not trace.input_redacted
    assert trace.playbook_id == "MONITOR"
    assert any(fact.key == "diagnostic.error_message" and fact.evidence_valid for fact in trace.extracted_facts)
    assert trace.decisions and trace.decisions[-1].source == "PYTHON_RULE"
    serialized = trace.model_dump_json().lower()
    assert "system_prompt" not in serialized and "conversation_context" not in serialized


def test_demo_explainability_redacts_explicit_secret(chat):
    secret = "Moje hasło to ExamplePassword123"
    response = chat.send(secret, explain=True)
    assert response.explainability is not None
    assert response.explainability.input_redacted
    assert "ExamplePassword123" not in response.explainability.model_dump_json()
