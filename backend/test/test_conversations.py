import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import AIProviderUnavailableError, AIProviderResponseError
from app.models.conversation import ConversationState, SecurityAssessment
from app.models.conversation import PendingQuestion
from app.models.incident import IncidentState
from app.db.models import MessageRecord, TicketRecord, ResolvedIncidentRecord
from app.services.playbook import start_diagnosis


def incident(subject, category="HARDWARE", family="DEVICE"):
    return dict(category=category, subcategory=subject, summary=f"Nie działa {subject}", issue_family=family)


def test_wifi_visible_local_failure_then_ticket(chat):
    chat.ai.expect(incident=incident("NETWORK", "NETWORK", "NETWORK"), facts={"connection_type": "WIFI"})
    assert "liście" in chat.send("Nie działa mi połączenie Wi-Fi").reply
    assert "inne" in chat.send("Tak").reply.lower()
    response = chat.send("Tak")
    assert "połącz" in response.reply and not response.ticket_id
    assert chat.state().diagnostic.pending_question.target == "feedback"
    calls = len(chat.ai.calls)
    response = chat.send("Nie")
    assert response.stage == "ESCALATED" and response.ticket_id
    assert len(chat.ai.calls) == calls


def test_wifi_free_text_answer_reconnects_before_ticket(chat):
    chat.ai.expect(incident=incident("NETWORK", "NETWORK", "NETWORK"),facts={})
    chat.send("Nie mogę połączyć się z internetem")
    assert "liście" in chat.send("Wi-Fi").reply
    assert "inne" in chat.send("Tak").reply.lower()
    chat.ai.expect(facts={"other_devices_work":True})
    result=chat.send("Mają dostęp do internetu")
    assert result.stage == "RESOLUTION" and "połącz" in result.reply
    assert not result.ticket_id


def test_wifi_refresh_checks_visibility_not_resolution(chat):
    chat.ai.expect(incident=incident("NETWORK", "NETWORK", "NETWORK"),
        facts={"connection_type": "WIFI", "network_visible": False, "other_devices_work": True})
    assert "Włącz Wi-Fi" in chat.send("Nie widzę sieci, u innych działa").reply
    result = chat.send("Tak")
    assert result.stage == "RESOLUTION" and "połącz" in result.reply
    assert not chat.state().incident.resolved


def test_completed_visibility_check_still_asks_for_visibility(chat):
    chat.ai.expect(incident=incident("NETWORK", "NETWORK", "NETWORK"),
        facts={"connection_type":"WIFI", "network_visible":False, "other_devices_work":True})
    chat.send("Nie widzę sieci, u innych działa")
                                                                                    
    chat.ai.expect(facts={}, feedback={"understood":True,"step_completed":True})
    result=chat.send("Wykonałem czynność, co dalej?")
    assert result.stage == "ACTIVE" and "liście" in result.reply
    assert chat.state().diagnostic.pending_question.target == "diagnostic"
    assert "połącz" in chat.send("Tak").reply


def test_shared_network_outage_skips_local_repairs(chat):
    chat.ai.expect(incident=incident("NETWORK", "NETWORK", "NETWORK"), facts={"connection_type":"ETHERNET", "other_devices_work":False})
    result = chat.send("Internet nie działa nikomu")
    assert result.stage == "ESCALATED"
    assert not chat.state().resolution.attempts


def test_ethernet_reseat_then_resolution(chat):
    chat.ai.expect(incident=incident("NETWORK", "NETWORK", "NETWORK"), facts={"connection_type":"ETHERNET", "other_devices_work":True})
    assert "Wyjmij wtyczkę" in chat.send("Nie działa internet przez kabel, u innych działa").reply
    result = chat.send("Tak")
    assert result.stage == "RESOLVED" and not result.ticket_id


def test_monitor_input_then_cable_then_ticket(chat):
    chat.ai.expect(incident=incident("MONITOR"), facts={"powered":True,"error_message":"NO SIGNAL"})
    assert "Input/Source" in chat.send("Monitor pokazuje No signal").reply
    assert "przewodu obrazu" in chat.send("Nie").reply
    assert chat.send("Nie").stage == "ESCALATED"
    assert len(chat.state().resolution.attempts) == 2


@pytest.mark.parametrize("question", ["Czy problem blokuje pracę?", "Czy masz obejście?", "Czy sprawa jest pilna?"])
def test_user_self_resolution_at_any_triage_question(chat, question):
    state = ConversationState(conversation_id="seed", incident=IncidentState(**incident("MONITOR")), last_question=question)
    state.diagnostic = start_diagnosis(state.incident, state.diagnostic)
    chat.seed(state)
    message = "Naprawiłem, wystarczyło przełączyć wejście sygnału z VGA na DP"
    chat.ai.expect(facts={}, feedback={"understood":True,"problem_resolved":True}, evidence=message)
    assert chat.send(message).stage == "RESOLVED"
    assert chat.state().resolution.user_resolution == message
    with Session(chat.engine) as db:
        saved = db.scalar(select(ResolvedIncidentRecord))
        assert message in saved.resolution and not saved.technician_verified
        assert db.scalar(select(TicketRecord)) is None


@pytest.mark.parametrize("feedback", [{"step_completed":True}, {"problem_resolved":False}, {}])
def test_partial_completion_never_closes(chat, feedback):
    chat.ai.expect(incident=incident("MONITOR"), facts={"powered":True,"error_message":"NO SIGNAL"})
    chat.send("Monitor pokazuje No signal")
    chat.ai.expect(facts={}, feedback={"understood":True, **feedback})
    assert chat.send("Przełączyłem wejście, co dalej?").stage != "RESOLVED"


def test_battery_cause_interrupts_bluetooth(chat):
    chat.ai.expect(incident=incident("MOUSE"),facts={"connection_type":"BLUETOOTH"})
    assert "zasilanie" in chat.send("Nie działa mysz Bluetooth").reply
    chat.ai.expect(facts={"battery_depleted":True})
    result=chat.send("Bateria się rozładowała")
    assert result.stage == "ESCALATED" and "baterii" in result.reply
    with Session(chat.engine) as db:
        assert db.scalar(select(TicketRecord)).routing["reason_code"] == "BATTERY_DEPLETED"


def test_scanner_consumable_is_service_request(chat):
    chat.ai.expect(incident={**incident("SCANNING"),"service_profile":"office_scanner"},facts={"error_message":"brak tuszu", "consumable_depleted":True})
    assert chat.send("Nie mogę skanować, pisze brak tuszu").stage == "ESCALATED"
    with Session(chat.engine) as db:
        ticket=db.scalar(select(TicketRecord))
        assert ticket.routing["ticket_kind"] == "SERVICE_REQUEST"
        assert ticket.routing["reason_code"] == "CONSUMABLE_DEPLETED"


def test_hazard_overrides_reported_success(chat):
    text="Monitor już działa, ale z obudowy leci dym"
    chat.ai.expect(incident={**incident("MONITOR"),"physical_hazard":True},facts={},
        feedback={"understood":True,"problem_resolved":True},evidence="Monitor już działa")
    result=chat.send(text)
    assert result.stage == "ESCALATED" and "Przerwij" in result.reply
    assert not chat.state().incident.resolved


def test_security_overrides_success_and_skips_diagnostics(chat):
    text="Naprawione, ale kliknąłem link phishingowy"
    chat.ai.expect(classification={"intent":"SECURITY_INCIDENT"},
        feedback={"understood":True,"problem_resolved":True},evidence="Naprawione")
    chat.ai.security=SecurityAssessment(event_type="PHISHING",evidence="kliknąłem link phishingowy")
    assert chat.send(text).stage == "ESCALATED"
    assert chat.ai.calls == ["interpret","security"]


def test_secret_never_reaches_ai_or_persistence(chat):
    secret="DemoOnlySecret123"
    assert chat.send(f"Moje hasło to {secret}").stage == "ESCALATED"
    assert not chat.ai.calls
    with Session(chat.engine) as db:
        assert all(secret not in m.content for m in db.scalars(select(MessageRecord)))


def test_timeout_does_not_advance_conversation(chat):
    chat.ai.expect(incident=incident("MONITOR"),facts={})
    chat.send("Nie działa monitor")
    before=chat.state().model_dump()
    chat.ai.messages.append(AIProviderUnavailableError("timeout"))
    with pytest.raises(AIProviderUnavailableError): chat.send("No signal")
    assert chat.state().model_dump() == before
    with Session(chat.engine) as db:
        assert len(list(db.scalars(select(MessageRecord)))) == 2


def test_false_resolution_without_evidence_rolls_back(chat):
    chat.ai.expect(incident=incident("MONITOR"),facts={}, feedback={"understood":True,"problem_resolved":True})
    with pytest.raises(AIProviderResponseError): chat.send("Nie działa monitor")
    with Session(chat.engine) as db:
        assert not list(db.scalars(select(MessageRecord)))


def test_outlook_comparison_is_not_resolution(chat):
    chat.ai.expect(incident=incident("OUTLOOK","EMAIL","ACCESS"),facts={"login_problem":True})
    assert "konto" in chat.send("Nie mogę zalogować się do Outlooka").reply
    assert "aktualnego hasła" in chat.send("Tak").reply
    assert "wygasło" in chat.send("Tak").reply
    assert "innego urządzenia" in chat.send("Nie").reply
    assert "drugim urządzeniu" in chat.send("Tak").reply
    chat.ai.expect(facts={"other_device_works":True})
    result=chat.send("Na drugim urządzeniu działa")
    assert result.stage != "RESOLVED"


def test_new_cable_hint_interrupts_business_triage(chat):
    state=ConversationState(conversation_id="seed",incident=IncidentState(**incident("PRINTING",family="PRINTING")),last_question="Czy masz obejście?")
    state.diagnostic=start_diagnosis(state.incident,state.diagnostic)
    chat.seed(state)
    chat.ai.expect(incident={"technical_observations":["Chyba odłączony kabel"]},facts={"cable_issue_suspected":True})
    result=chat.send("Problem to chyba odłączony kabel od internetu")
    assert result.stage == "RESOLUTION" and "sprawdźmy kabel" in result.reply


def test_suspected_battery_does_not_create_supply_ticket(chat):
    chat.ai.expect(incident=incident("MOUSE"),facts={"connection_type":"BLUETOOTH","battery_depleted":True},uncertain=["battery_depleted"])
    result=chat.send("Mysz Bluetooth nie działa, może bateria")
    assert result.stage != "ESCALATED"
    assert "battery_depleted" not in chat.state().diagnostic.facts


@pytest.mark.parametrize("claimed_resolution", [False, True])
def test_printer_power_on_is_not_the_original_resolution(chat, claimed_resolution):
    chat.ai.expect(incident=incident("PRINTING",family="PRINTING"),facts={"printer_powered":False})
    assert "Włącz drukarkę" in chat.send("Drukarka nie włącza się").reply
    chat.ai.expect(facts={"printer_powered":True,"printer_status":"OFFLINE"},
        feedback={"understood":True,"step_completed":True,"problem_resolved":claimed_resolution},
        evidence="Włączyła się" if claimed_resolution else None)
    response=chat.send("Włączyła się, ale nadal offline")
    assert response.stage == "ACTIVE" and "liście" in response.reply
    assert chat.state().resolution.attempts[-1].problem_resolved is False


def test_unknown_answer_does_not_repeat_forever(chat):
    chat.ai.expect(incident=incident("MONITOR"),facts={})
    chat.send("Nie działa monitor")
    for _ in range(2):
        chat.ai.expect(facts={})
        response=chat.send("Nie rozumiem pytania")
    assert response.stage == "ESCALATED" and "Nie będę powtarzać" in response.reply


def test_vpn_locked_account_stops_before_reconnecting(chat):
    chat.ai.expect(incident=incident("VPN","NETWORK","ACCESS"),facts={"account_locked":True,"normal_internet_works":True,"vpn_client_starts":True,"vpn_connection_status":"FAILED"})
    response=chat.send("VPN nie działa, konto zablokowane")
    assert response.stage == "ESCALATED" and not chat.state().resolution.attempts


def test_printer_connection_choice_cannot_invent_connected_status(chat):
    state=ConversationState(conversation_id="seed",incident=IncidentState(**incident("PRINTING",family="PRINTING")))
    state.diagnostic=start_diagnosis(state.incident,state.diagnostic)
    state.diagnostic.facts={"printer_powered":True,"printer_visible":False}
    state.diagnostic.pending_fact="connection_type"
    state.diagnostic.pending_question=PendingQuestion(question_id="DIAGNOSTIC:PRINTING:connection_type",fact_key="connection_type",target="diagnostic")
    chat.seed(state)
    response=chat.send("Przez Wi-Fi")
    assert "siecią" in response.reply and not chat.ai.calls
    assert chat.state().diagnostic.facts["connection_type"] == "WI-FI"
    assert "wifi_connected" not in chat.state().diagnostic.facts


def test_mouse_connection_choice_uses_no_ai(chat):
    chat.ai.expect(incident=incident("MOUSE"),facts={})
    chat.send("Nie działa mysz")
    calls=list(chat.ai.calls)
    assert "zasilanie" in chat.send("Przez bluetooth").reply
    assert chat.ai.calls == calls
