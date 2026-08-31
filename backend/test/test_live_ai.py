import os

import pytest

from app.ai.ollama_provider import OllamaProvider
from app.models.conversation import ConversationState, MessageContext
from app.models.incident import IncidentState
from app.services.playbook import start_diagnosis

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.getenv("RUN_LIVE_AI") != "1", reason="Set RUN_LIVE_AI=1 for Ollama replays")]


class ReplayAI(OllamaProvider):
    def analyze_message(self, message, context):
        result=super().analyze_message(message, context)
        print("interpret", result.model_dump(exclude_none=True), flush=True)
        return result

    def analyze_diagnostic_response(self, **kwargs):
        result=super().analyze_diagnostic_response(**kwargs)
        print("facts", result.model_dump(exclude_none=True), flush=True)
        return result


@pytest.mark.parametrize("message,expected", [
    ("Naprawiłem, wystarczyło przełączyć wejście sygnału z VGA na DP", True),
    ("Już działa, dziękuję", True),
    ("U wszystkich innych osób działają monitory", None),
    ("Zrobiłem to, co dalej?", None),
    ("Jeszcze nie naprawiłem, nadal brak sygnału", False),
])
def test_resolution_interpretation(message, expected):
    ai=ReplayAI()
    context=MessageContext(incident=IncidentState(category="HARDWARE",subcategory="MONITOR",summary="Nie działa monitor"),last_question="Czy sprawa jest pilna?")
    result=ai.analyze_message(message,context)
    assert result.feedback.problem_resolved is expected


def test_monitor_dialogue(chat):
    chat.ai=ReplayAI()
    first=chat.send("Nie działa mi monitor")
    assert first.stage == "ACTIVE" and "monitor" in first.reply.lower()
    second=chat.send("No signal")
    assert second.stage == "RESOLUTION" and "Input/Source" in second.reply
    third=chat.send("Naprawiłem, wystarczyło przełączyć wejście sygnału z VGA na DP")
    assert third.stage == "RESOLVED"


def test_wifi_dialogue(chat):
    chat.ai=ReplayAI()
    assert "liście" in chat.send("Nie działa mi połączenie Wi-Fi").reply
    assert "inne" in chat.send("Tak").reply.lower()
    assert "połącz" in chat.send("Tak").reply
    assert chat.send("Po ponownym połączeniu nadal nie ma internetu").stage == "ESCALATED"


def test_wifi_screenshot_free_text_answer(chat):
    chat.ai=ReplayAI()
    assert "Wi-Fi czy kabel" in chat.send("Nie mogę połączyć się z internetem").reply
    assert "liście" in chat.send("Wi-Fi").reply
    assert "inne" in chat.send("Tak").reply.lower()
    result=chat.send("Mają dostęp do internetu")
    assert result.stage == "RESOLUTION" and "połącz" in result.reply
    assert not result.ticket_id


def test_printer_dialogue(chat):
    chat.ai=ReplayAI()
    first=chat.send("Mam problem z drukarką, nie włącza się")
    assert first.stage == "RESOLUTION" and "Włącz drukarkę" in first.reply
    second=chat.send("Włączyła się, wyświetla napis offline")
    assert second.stage != "RESOLVED" and "liście" in second.reply
    third=chat.send("To nowa drukarka, nie ma jej na liście, mam ją wyszukać?")
    assert third.stage != "ESCALATED"
    fourth=chat.send("Przez Wi-Fi")
    assert "siecią" in fourth.reply
    fifth=chat.send("Jest połączona z siecią firmową")
    assert fifth.stage == "RESOLUTION" and "wyszukania" in fifth.reply


def test_battery_dialogue(chat):
    chat.ai=ReplayAI()
    assert "podłączone" in chat.send("Nie działa mi myszka").reply
    assert "zasilanie" in chat.send("Przez bluetooth").reply
    result=chat.send("Bateria się rozładowała")
    assert result.stage == "ESCALATED" and "baterii" in result.reply


def test_outlook_dialogue(chat):
    chat.ai=ReplayAI()
    assert "konto" in chat.send("Nie mogę zalogować się do Outlooka").reply
    assert "aktualnego hasła" in chat.send("Tak").reply
    assert "wygasło" in chat.send("Tak").reply
    assert "innego urządzenia" in chat.send("Nie").reply
    assert "drugim urządzeniu" in chat.send("Tak").reply
    assert chat.send("Na drugim urządzeniu Outlook działa").stage != "RESOLVED"


def test_phishing_dialogue(chat):
    chat.ai=ReplayAI()
    result=chat.send("Kliknąłem w link i przeniosło mnie na stronę z fałszywym oprogramowaniem")
    assert result.stage == "ESCALATED" and chat.state().security_emergency


def test_vpn_dialogue(chat):
    chat.ai=ReplayAI()
    result=chat.send("VPN nie łączy, zwykły internet działa, aplikacja uruchamia się, ale pokazuje błąd połączenia")
    assert result.stage == "RESOLUTION" and "VPN" in result.reply


def test_scanner_toner_dialogue(chat):
    chat.ai=ReplayAI()
    chat.send("Nie mogę zeskanować dokumentu")
    result=chat.send("Piszę brak tuszu w tonerze")
    assert result.stage == "ESCALATED" and "tuszu" in result.reply


def test_forgotten_password_keeps_demo_separate(chat, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "password_reset_demo_enabled", True)
    chat.ai=ReplayAI()
    result=chat.send("Zapomniałem hasła do Outlooka")
    assert result.password_reset_demo_available and result.stage == "ACTIVE"
    assert "Nie wysyłam prawdziwego maila" in result.reply
