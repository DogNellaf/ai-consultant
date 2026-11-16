import pytest

from app import config
from app.engine import DEMO_CONTACTS, MANAGER, Session


@pytest.mark.parametrize("intent", ["message", "question"])
@pytest.mark.parametrize("demo", [False, True])
def test_new_question_matching_submitted_summary_is_answered(client, service, monkeypatch, intent, demo):
    monkeypatch.setattr(config, "DEMO_LEADS", demo)
    result = client.post("/api/chat", json={"text": MANAGER}).json()
    sid = result["session_id"]
    summary = "Сколько стоит доставка?"
    for index, text in enumerate(("Тестовый Гость", "+70000000000", summary)):
        body = {"session_id": sid, "text": text, "form_token": result["form_token"], "request_id": f"step-{index}"}
        result = client.post("/api/chat", json=body).json()
    assert result["kind"] == "lead_done"
    reply = client.post(
        "/api/chat",
        json={
            "session_id": sid,
            "text": summary,
            "form_token": result["form_token"],
            "request_id": "new-question",
            "intent": intent,
        },
    ).json()
    assert reply["kind"] == "answer" and reply["sources"]
    assert reply["remaining"] == result["remaining"] - 1
    replay = client.post("/api/chat", json=body).json()
    assert replay["kind"] == "lead_done" and replay["lead_id"] == result["lead_id"]
    assert len(service.store.leads) + service.consultant.demo_leads == 1


def test_engine_answers_question_matching_submitted_summary(consultant, monkeypatch):
    monkeypatch.setattr(config, "DEMO_LEADS", True)
    s = Session("review", "widget")
    for text in (MANAGER, DEMO_CONTACTS, "Сколько стоит доставка?"):
        reply = consultant.handle(s, text)
    assert reply.kind == "lead_done"
    reply = consultant.handle(s, "Сколько стоит доставка?")
    assert reply.kind == "answer" and reply.sources


@pytest.mark.parametrize("step", ["name", "phone", "summary"])
def test_file_operations_preserve_active_form_actions(client, service, monkeypatch, step):
    monkeypatch.setattr(config, "DEMO_LEADS", True)
    current = client.post("/api/chat", json={"text": MANAGER}).json()
    sid = current["session_id"]
    if step == "phone":
        current = client.post("/api/chat", json={"session_id": sid, "text": "Тестовый Гость"}).json()
    elif step == "summary":
        current = client.post("/api/chat", json={"session_id": sid, "text": DEMO_CONTACTS}).json()
    for name, content, status in (
        ("rules.md", b"## Rules\nDelivery costs 250 roubles.", 200),
        ("empty.md", b"## Empty", 400),
    ):
        response = client.post("/api/upload", data={"session_id": sid}, files={"file": (name, content)})
        assert response.status_code == status
        data = response.json()
        assert data["form_active"] is True and data["buttons"] == current["buttons"]
        assert data["form_token"] == current["form_token"]
        assert service.sessions[sid][0].lead.step == step
    deleted = client.post("/api/upload/delete", json={"session_id": sid}).json()
    assert deleted["buttons"] == current["buttons"] and deleted["upload"] == ""
    assert service.sessions[sid][0].lead.step == step
    cancelled = client.post("/api/chat", json={"session_id": sid, "text": "Отмена"}).json()
    assert cancelled["form_active"] is False
