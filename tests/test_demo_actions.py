import pytest

from app import config
from app.engine import DEMO_CONTACTS, MANAGER


@pytest.mark.parametrize("step", ["name", "phone", "summary"])
def test_page_question_never_fills_or_finishes_a_form(client, service, monkeypatch, step):
    monkeypatch.setattr(config, "DEMO_LEADS", True)
    current = client.post("/api/chat", json={"text": MANAGER}).json()
    sid = current["session_id"]
    if step == "phone":
        current = client.post("/api/chat", json={"session_id": sid, "text": "Тестовый Гость"}).json()
    elif step == "summary":
        current = client.post("/api/chat", json={"session_id": sid, "text": DEMO_CONTACTS}).json()
    body = {
        "session_id": sid,
        "text": "Сколько стоит доставка?",
        "intent": "question",
        "form_token": current["form_token"],
        "request_id": "page-question",
    }
    reply = client.post("/api/chat", json=body).json()
    assert reply == current
    form = service.sessions[sid][0].lead
    assert form.step == step
    assert form.name != body["text"]
    assert service.consultant.demo_leads == 0 and not service.store.leads


def test_page_question_outside_form_is_answered_and_charged_once(client):
    body = {"text": "Сколько стоит доставка?", "intent": "question", "request_id": "page-question"}
    reply = client.post("/api/chat", json=body).json()
    assert reply["kind"] == "answer" and reply["remaining"] == config.MESSAGES_PER_DAY - 1
    replay = client.post("/api/chat", json={**body, "session_id": reply["session_id"]}).json()
    assert replay == reply


def test_request_identity_includes_question_intent(client, service):
    first = client.post("/api/chat", json={"text": MANAGER, "intent": "question", "request_id": "operation"}).json()
    changed = client.post(
        "/api/chat", json={"session_id": first["session_id"], "text": MANAGER, "request_id": "operation"}
    ).json()
    assert changed["kind"] == "error"
    assert service.sessions[first["session_id"]][0].lead.step == "name"


def test_resume_recovers_current_prompt_after_discarding_a_lost_phone_reply(client):
    current = client.post("/api/chat", json={"text": MANAGER}).json()
    sid = current["session_id"]
    for text in ("Тестовый Гость", "+70000000000"):
        current = client.post("/api/chat", json={"session_id": sid, "text": text}).json()
    resumed = client.post("/api/session", json={"session_id": sid}).json()
    assert resumed["form_active"] is True
    assert resumed["form_token"] == current["form_token"]
    assert resumed["form_reply"]["text"] == current["text"]
    assert "Что передать менеджеру?" in resumed["form_reply"]["text"]
    client.post("/api/chat", json={"session_id": sid, "text": "Отмена"})
    resumed = client.post("/api/session", json={"session_id": sid}).json()
    assert resumed["form_active"] is False and "form_reply" not in resumed
