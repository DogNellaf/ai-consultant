import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import config
from app.api import app
from app.engine import MANAGER
from tests.conftest import FakeLLM


@pytest.mark.parametrize("channel", ["widget", "telegram"])
def test_expired_phone_form_does_not_reach_history_or_model(client, service, channel):
    service.consultant.llm = FakeLLM()
    sid = client.post("/api/chat", json={"channel": channel, "text": MANAGER}).json()["session_id"]
    client.post("/api/chat", json={"session_id": sid, "text": "Тестовый Гость"})
    assert service.sessions[sid][0].lead.step == "phone"
    s = service.sessions[sid][0]
    service.sessions[sid] = (s, 0)
    service._expire()
    r = client.post("/api/chat", json={"session_id": sid, "text": "+7 000 000-00-00"}).json()
    assert r["kind"] == "session_expired" and r["session_id"] is None
    assert sid not in service.sessions and not s.history
    assert service.consultant.llm.calls == []
    # Only an explicit new conversation resumes normal questions, without the rejected phone.
    new = client.post("/api/chat", json={"text": ""}).json()
    assert new["session_id"] != sid
    client.post("/api/chat", json={"session_id": new["session_id"], "text": "Сколько стоит доставка?"})
    assert "70000000000" not in str(service.consultant.llm.calls)
    assert "+7 000" not in str(service.consultant.llm.calls)


def test_resume_checks_state_without_restarting_an_existing_form(client, service):
    sid = client.post("/api/chat", json={"text": MANAGER}).json()["session_id"]
    r = client.post("/api/session", json={"session_id": sid}).json()
    assert r["kind"] == "session" and r["session_id"] == sid
    assert service.sessions[sid][0].lead.step == "name"
    client.post("/api/session/delete", json={"session_id": sid})
    assert client.post("/api/session", json={"session_id": sid}).json()["kind"] == "session_expired"


def test_expired_upload_token_does_not_create_an_orphan_collection(client, service):
    for path in ("/api/upload", "/api/upload/delete"):
        if path.endswith("/delete"):
            r = client.post(path, json={"session_id": "expired"})
        else:
            r = client.post(path, data={"session_id": "expired"}, files={"file": ("notes.txt", b"Private text")})
        assert r.json()["kind"] == "session_expired"
    assert not service.sessions
    assert service.consultant.searcher.chunks(["upload:expired"]) == []


@pytest.mark.parametrize("cancel_upload", [False, True])
def test_delete_waits_for_indexing_and_removes_late_fragments(service, monkeypatch, cancel_upload):
    entered, release = threading.Event(), threading.Event()
    original = service.consultant.searcher.index

    def delayed_index(collection, chunks):
        entered.set()
        assert release.wait(10)
        return original(collection, chunks)

    monkeypatch.setattr(service.consultant.searcher, "index", delayed_index)
    s = service.session(None, "widget")

    async def scenario():
        pending = asyncio.create_task(service.upload(s, "private.md", b"## Private\nDocument content."))
        assert await asyncio.to_thread(entered.wait, 5)
        if cancel_upload:
            pending.cancel()
        deleted = [asyncio.create_task(service.delete(s.id)) for _ in range(2)]
        await asyncio.sleep(0.02)
        assert all(not task.done() for task in deleted)
        assert service.resolve(s.id, "widget") is None
        release.set()
        if cancel_upload:
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            assert (await pending).kind == "session_expired"
        await asyncio.gather(*deleted)

    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert not service.sessions and not service._deleting
    assert service.consultant.searcher.chunks([f"upload:{s.id}"]) == []
    assert not s.upload and not s.history


def test_queued_question_is_not_sent_to_model_after_delete(service):
    service.consultant.llm = FakeLLM()
    s = service.session(None, "widget")

    async def scenario():
        await service._sem.acquire()
        pending = asyncio.create_task(service.ask(s, "v", "Сколько стоит доставка?"))
        while service._waiting == 0:
            await asyncio.sleep(0)
        deletion = asyncio.create_task(service.delete(s.id))
        await asyncio.sleep(0)
        service._sem.release()
        assert (await pending).kind == "session_expired"
        await deletion

    asyncio.run(scenario())
    assert not service.consultant.llm.calls
    assert service.remaining("v") == config.MESSAGES_PER_DAY


def test_parallel_http_confirmations_save_and_notify_once(service, monkeypatch):
    monkeypatch.setattr(config, "DEMO_LEADS", False)
    entered, release = threading.Event(), threading.Event()
    notified = []

    def notify(lead):
        notified.append(lead.id)
        entered.set()
        assert release.wait(10)
        return True

    service.consultant.notify = notify
    app.state.service = service

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            sid = (await client.post("/api/chat", json={"text": MANAGER})).json()["session_id"]
            for text in ("Тестовый Гость", "+7 000 000-00-00"):
                await client.post("/api/chat", json={"session_id": sid, "text": text})
            payload = {"session_id": sid, "text": "Уточнить доставку"}
            first = asyncio.create_task(client.post("/api/chat", json=payload))
            assert await asyncio.to_thread(entered.wait, 5)
            second = asyncio.create_task(client.post("/api/chat", json=payload))
            await asyncio.sleep(0.02)
            assert len(service.store.leads) == 1
            release.set()
            replies = [r.json() for r in await asyncio.gather(first, second)]
            assert all(r["kind"] == "lead_done" for r in replies)
            assert replies[0]["lead_id"] == replies[1]["lead_id"]
            # A network retry remains idempotent even after the question quota is exhausted.
            monkeypatch.setattr(config, "MESSAGES_PER_DAY", 0)
            assert (await client.post("/api/chat", json=payload)).json()["lead_id"] == replies[0]["lead_id"]
            # An explicitly new form can still submit a new enquiry with the same summary.
            for text in (MANAGER, "Другой Гость", "+7 000 000-00-00", "Уточнить доставку"):
                last = (await client.post("/api/chat", json={"session_id": sid, "text": text})).json()
            assert last["lead_id"] != replies[0]["lead_id"]

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        del app.state.service
    assert len(service.store.leads) == len(notified) == 2


def test_completed_demo_reply_is_not_added_to_model_history_and_expires(service, monkeypatch):
    monkeypatch.setattr(config, "DEMO_LEADS", True)
    s = service.session(None, "widget")

    async def scenario():
        for text in (MANAGER, "Тестовый Гость", "+7 000 000-00-00", "Уточнить торт"):
            reply = await service.ask(s, "v", text)
        assert (await service.ask(s, "v", "Уточнить торт")).lead_id == reply.lead_id

    asyncio.run(scenario())
    assert not s.history and s.completed_lead is not None
    service.sessions[s.id] = (s, 0)
    service._expire()
    assert s.completed_lead is None and not s.completed_lead_text


def test_telegram_requires_start_after_server_state_is_lost(service, monkeypatch):
    from app import bot

    monkeypatch.setattr(bot, "SERVICE", service)
    service.consultant.llm = FakeLLM()
    message = SimpleNamespace(
        chat=SimpleNamespace(id=17), from_user=SimpleNamespace(id=17), text="+7 000 000-00-00", answer=AsyncMock()
    )

    async def scenario():
        s = service.session("tg17", "telegram")
        for text in (MANAGER, "Тестовый Гость"):
            await service.ask(s, "v", text)
        service.forget(s.id)
        await bot.text(message)
        assert not service.sessions and not service.consultant.llm.calls
        assert "/start" in message.answer.call_args.args[0]
        await bot.start(message)
        assert service.sessions["tg17"][0].lead is None
        message.text = "Сколько стоит доставка?"
        await bot.text(message)

    asyncio.run(scenario())
    assert "+7 000" not in str(service.consultant.llm.calls)
