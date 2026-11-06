import pytest
from fastapi.testclient import TestClient

from app.api import app


@pytest.fixture
def client(service):
    app.state.service = service
    with TestClient(app) as c:
        yield c
    del app.state.service


def test_chat_keeps_session_and_counts(client):
    r = client.post("/api/chat", json={"text": "Можно забрать заказ самому?"}).json()
    assert r["kind"] == "answer" and r["sources"][0]["source"] == "delivery.md"
    assert r["remaining"] == 9
    r2 = client.post("/api/chat", json={"session_id": r["session_id"], "text": "Позвать менеджера"}).json()
    assert r2["session_id"] == r["session_id"] and r2["kind"] == "lead"


def test_upload_and_delete(client):
    r = client.post("/api/upload", files={"file": ("menu.txt", "Пирог с тыквой по пятницам.".encode())}).json()
    assert r["kind"] == "upload" and r["upload"] == "menu.txt"
    d = client.post("/api/upload/delete", json={"session_id": r["session_id"]}).json()
    assert d["upload"] == ""


def test_bad_upload_is_400(client):
    r = client.post("/api/upload", files={"file": ("photo.jpg", b"x")})
    assert r.status_code == 400 and r.json()["kind"] == "error"


def test_widget_and_demo_page(client):
    assert client.get("/widget.js").status_code == 200
    assert client.get("/widget.css").status_code == 200
    assert client.get("/kb-search.js").status_code == 200
    assert "widget.js" in client.get("/").text
    assert 'data-mode="browser"' in client.get("/browser.html").text
    assert client.get("/health").json() == {"ok": True}


def test_widget_texts_match_the_engine():
    """Browser mode repeats app/engine.py in JS: the visitor sees the same words in both modes."""
    from pathlib import Path

    from app import engine

    js = (Path(engine.__file__).parent.parent / "widget" / "widget.js").read_text(encoding="utf-8")
    for text in [
        engine.MANAGER,
        engine.CANCEL,
        engine.KEEP,
        *engine.EXAMPLES,
        "В базе знаний нет ответа на этот вопрос, гадать не буду.",
        "Передам вопрос менеджеру вместе с нашей перепиской. Как к вам обращаться?",
        "Не похоже на номер. Например: +7 900 123-45-67.",
    ]:
        assert text in js, text
    assert engine.HANDOFF.pattern.replace("\\w*", "[а-яё]*") in js
