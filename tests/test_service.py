import asyncio

from app import config
from app.engine import MANAGER
from app.notify import lead_text
from app.store import Lead
from tests.conftest import FakeLLM


def run(coro):
    return asyncio.run(coro)


def test_daily_limit_stops_politely(service, monkeypatch):
    monkeypatch.setattr(config, "MESSAGES_PER_DAY", 2)
    s = service.session(None, "widget")
    assert run(service.ask(s, "v1", "Когда вы открыты?")).kind == "answer"
    assert run(service.ask(s, "v1", "Есть курсовая по истории?")).kind == "unknown"
    r = run(service.ask(s, "v1", "Сколько стоит доставка?"))
    assert r.kind == "limit" and "2 вопросов" in r.text
    assert service.remaining("v1") == 0
    assert service.remaining("v2") == 2


def test_lead_form_does_not_spend_the_limit(service, monkeypatch):
    monkeypatch.setattr(config, "MESSAGES_PER_DAY", 1)
    s = service.session(None, "widget")
    run(service.ask(s, "v1", "Когда вы открыты?"))
    assert service.remaining("v1") == 0
    for text in (MANAGER, "Анна", "+7 900 123 45 67", "Торт"):
        r = run(service.ask(s, "v1", text))
    assert r.kind == "lead_done"


def test_budget_switches_model_off(service, monkeypatch):
    service.consultant.llm = FakeLLM(tokens=600)
    monkeypatch.setattr(config, "DAILY_TOKEN_BUDGET", 1000)
    s = service.session(None, "widget")
    assert run(service.ask(s, "v1", "Сколько стоит доставка?")).mode == "fake"
    assert run(service.ask(s, "v2", "Сколько стоит доставка?")).mode == "fake"
    assert service.store.tokens_today() == 1200
    r = run(service.ask(s, "v3", "Можно забрать заказ самому?"))
    assert r.mode == "fragments" and r.kind == "answer"
    assert len(service.consultant.llm.calls) == 2


def test_queue_full_asks_to_wait(service, monkeypatch):
    service.consultant.llm = FakeLLM()
    monkeypatch.setattr(config, "QUEUE_MAX", 0)
    r = run(service.ask(service.session(None, "widget"), "v1", "Сколько стоит доставка?"))
    assert r.kind == "busy"


def test_empty_text_greets(service):
    r = run(service.ask(service.session(None, "widget"), "v1", "  "))
    assert r.kind == "greeting" and MANAGER in r.buttons


def test_session_expires_with_its_upload(service, monkeypatch):
    s = service.session(None, "widget")
    run(service.upload(s, "notes.txt", "Пароль от вайфая в зале: колосок2026.".encode()))
    assert service.consultant.searcher.chunks([f"upload:{s.id}"])
    monkeypatch.setattr(config, "SESSION_TTL", -1)
    service.session(None, "widget")
    assert s.id not in service.sessions
    assert service.consultant.searcher.chunks([f"upload:{s.id}"]) == []


def test_upload_is_searched_with_the_base(service):
    s = service.session(None, "widget")
    r = run(service.upload(s, "menu.txt", "Сезонный пирог с тыквой продаётся только по пятницам.".encode()))
    assert r.kind == "upload" and "1 фрагмент." in r.text
    a = run(service.ask(s, "v1", "Когда бывает пирог с тыквой?"))
    assert a.kind == "answer" and a.sources[0]["source"] == "menu.txt"
    run(service.drop_upload(s))
    assert service.consultant.searcher.chunks([f"upload:{s.id}"]) == []


def test_lead_text_escapes_and_includes_dialog():
    lead = Lead("<b>Анна</b>", "+79001234567", "Торт", "widget", history=[{"role": "user", "content": "1 < 2"}], id=7)
    text = lead_text(lead)
    assert "Заявка №7" in text and "&lt;b&gt;Анна" in text and "Клиент: 1 &lt; 2" in text
