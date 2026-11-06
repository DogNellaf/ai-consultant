import pytest

from app import config
from app.engine import CANCEL, KEEP, MANAGER, Session, normalize_phone
from app.llm import LLMError
from tests.conftest import FakeLLM


def ask(consultant, s, text, model=True):
    return consultant.handle(s, text, model)


def test_answer_is_the_fragment_with_its_source(consultant):
    s = Session("s1", "widget")
    r = ask(consultant, s, "Можно забрать заказ самому?")
    assert r.kind == "answer" and r.mode == "fragments"
    assert r.sources[0]["title"] == "Доставка и оплата › Самовывоз"
    assert "Садовой, 12" in r.text
    assert r.counted
    assert len(r.search) == 3


def test_off_topic_gets_honest_unknown(consultant):
    r = ask(consultant, Session("s1", "widget"), "Помогите написать курсовую по истории")
    assert r.kind == "unknown"
    assert r.sources == []
    assert MANAGER in r.buttons
    assert r.search  # "how it searched" still shows what was looked at


def test_model_writes_answer_from_fragments(consultant):
    consultant.llm = FakeLLM("Доставка по городу стоит 250 ₽.")
    r = ask(consultant, Session("s1", "widget"), "Сколько стоит доставка?")
    assert r.kind == "answer" and r.mode == "fake" and r.tokens == 120
    system, messages = consultant.llm.calls[0]
    assert "Доставка по городу" in system
    assert messages[-1] == {"role": "user", "content": "Сколько стоит доставка?"}


def test_model_unknown_marker(consultant):
    consultant.llm = FakeLLM("НЕ_ЗНАЮ")
    r = ask(consultant, Session("s1", "widget"), "Сколько стоит доставка?")
    assert r.kind == "unknown" and r.mode == "fake"


def test_model_failure_falls_back_to_fragments(consultant):
    consultant.llm = FakeLLM(error=LLMError("429"))
    r = ask(consultant, Session("s1", "widget"), "Можно забрать заказ самому?")
    assert r.kind == "answer" and r.mode == "fragments"


def test_model_is_not_called_when_switched_off(consultant):
    consultant.llm = FakeLLM()
    r = ask(consultant, Session("s1", "widget"), "Можно забрать заказ самому?", model=False)
    assert r.mode == "fragments" and consultant.llm.calls == []


def test_lead_form_saves_lead_with_dialog(consultant, store, sent):
    s = Session("s1", "widget")
    ask(consultant, s, "Когда вы открыты?")
    assert ask(consultant, s, MANAGER).kind == "lead"
    assert "цифр" in ask(consultant, s, "R2D2").text
    ask(consultant, s, "Анна")
    assert "Не похоже" in ask(consultant, s, "12345").text
    r = ask(consultant, s, "8 (900) 123-45-67")
    assert KEEP in r.buttons and "Когда вы открыты?" in r.text
    done = ask(consultant, s, KEEP)
    assert done.kind == "lead_done" and done.lead_id == 1
    lead = store.leads[0]
    assert (lead.name, lead.phone, lead.summary) == ("Анна", "+79001234567", "Когда вы открыты?")
    assert lead.history[0] == {"role": "user", "content": "Когда вы открыты?"}
    assert sent == [lead]
    assert s.lead is None
    assert not done.counted


def test_demo_lead_is_shown_not_kept(consultant, store, sent, monkeypatch):
    monkeypatch.setattr(config, "DEMO_LEADS", True)
    s = Session("s1", "widget")
    ask(consultant, s, "Когда вы открыты?")
    for text in (MANAGER, "Анна", "8 900 123-45-67"):
        ask(consultant, s, text)
    done = ask(consultant, s, KEEP)
    assert done.kind == "lead_done" and done.lead_id == 1 and "никуда не ушла" in done.text
    assert store.leads == [] and sent == [] and s.lead is None
    preview = done.manager_preview
    assert preview.startswith("Заявка №1 · виджет на сайте\nИмя: Анна\nТелефон: +79001234567")
    assert "Клиент: Когда вы открыты?" in preview and "<b>" not in preview
    for text in (MANAGER, "Олег", "+7 900 765 43 21", "Торт на субботу"):
        again = ask(consultant, s, text)
    assert again.lead_id == 2


def test_handoff_phrase_starts_form_with_its_text(consultant):
    s = Session("s1", "widget")
    assert ask(consultant, s, "Хочу оформить заказ на торт к субботе").kind == "lead"
    assert s.lead.question == "Хочу оформить заказ на торт к субботе"


def test_cancel_lead_form(consultant, store):
    s = Session("s1", "widget")
    ask(consultant, s, MANAGER)
    r = ask(consultant, s, CANCEL)
    assert s.lead is None and store.leads == [] and "не передаю" in r.text


def test_notification_failure_keeps_the_lead(consultant, store):
    def boom(lead):
        raise RuntimeError("telegram down")

    consultant.notify = boom
    s = Session("s1", "widget")
    for text in (MANAGER, "Анна", "+7 900 123 45 67", "Торт на субботу"):
        r = ask(consultant, s, text)
    assert r.kind == "lead_done" and "Она сохранена, менеджер перезвонит" in r.text
    assert len(store.leads) == 1


@pytest.mark.parametrize(
    "raw,phone",
    [
        ("+7 900 123-45-67", "+79001234567"),
        ("89001234567", "+79001234567"),
        ("9001234567", "+79001234567"),
        ("+33 6 12 34 56 78", "+33612345678"),
        ("123", None),
        ("телефон", None),
    ],
)
def test_normalize_phone(raw, phone):
    assert normalize_phone(raw) == phone
