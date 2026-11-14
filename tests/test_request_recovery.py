import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import config
from app.api import app
from app.engine import MANAGER
from app.llm import Completion


@pytest.mark.parametrize("demo", [False, True])
def test_each_form_step_replays_once_without_advancing(client, service, monkeypatch, demo):
    monkeypatch.setattr(config, "DEMO_LEADS", demo)
    result = client.post("/api/chat", json={"text": ""}).json()
    sid = result["session_id"]
    for index, (text, step) in enumerate(
        [(MANAGER, "name"), ("Тестовый Гость", "phone"), ("+70000000000", "summary"), ("Уточнить торт", None)]
    ):
        body = {
            "session_id": sid,
            "request_id": f"step-{index}",
            "form_token": result["form_token"],
            "text": text,
        }
        result = client.post("/api/chat", json=body).json()
        assert client.post("/api/chat", json=body).json() == result
        form = service.sessions[sid][0].lead
        assert (form.step if form else None) == step
        if step:
            assert not service.store.leads and not service.consultant.demo_leads
    assert result["kind"] == "lead_done"
    assert len(service.store.leads) + service.consultant.demo_leads == 1
    if not demo:
        assert service.store.leads[0].summary == "Уточнить торт"


def test_stale_step_token_does_not_turn_double_manager_click_into_name(client, service):
    hello = client.post("/api/chat", json={"text": ""}).json()
    body = {"session_id": hello["session_id"], "text": MANAGER, "form_token": hello["form_token"]}
    first = client.post("/api/chat", json={**body, "request_id": "first-click"}).json()
    repeated = client.post("/api/chat", json={**body, "request_id": "second-click"}).json()
    assert repeated == first
    form = service.sessions[hello["session_id"]][0].lead
    assert form.step == "name" and not form.name


def test_parallel_phone_retries_advance_only_once(service, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = service.consultant.handle

    def delayed(s, text, use_model):
        if text == "+70000000000":
            entered.set()
            assert release.wait(10)
        return original(s, text, use_model)

    monkeypatch.setattr(service.consultant, "handle", delayed)
    app.state.service = service

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            result = (await client.post("/api/chat", json={"text": MANAGER})).json()
            sid = result["session_id"]
            result = (await client.post("/api/chat", json={"session_id": sid, "text": "Тестовый Гость"})).json()
            body = {
                "session_id": sid,
                "text": "+70000000000",
                "request_id": "phone",
                "form_token": result["form_token"],
            }
            first = asyncio.create_task(client.post("/api/chat", json=body))
            assert await asyncio.to_thread(entered.wait, 5)
            second = asyncio.create_task(client.post("/api/chat", json=body))
            await asyncio.sleep(0)
            release.set()
            results = [r.json() for r in await asyncio.gather(first, second)]
            assert results[0] == results[1] and results[0]["kind"] == "lead"
            assert service.sessions[sid][0].lead.step == "summary"

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        del app.state.service
    assert not service.store.leads


def test_stale_token_still_protects_a_step_after_request_cache_eviction(client, service):
    hello = client.post("/api/chat", json={"text": ""}).json()
    sid = hello["session_id"]
    old = {"session_id": sid, "text": MANAGER, "request_id": "old", "form_token": hello["form_token"]}
    result = client.post("/api/chat", json=old).json()
    service.sessions[sid][0].requests.clear()
    assert client.post("/api/chat", json=old).json() == result
    assert service.sessions[sid][0].lead.step == "name"


def test_request_id_cannot_be_reused_with_different_data(client, service):
    first = client.post("/api/chat", json={"text": MANAGER, "request_id": "operation"}).json()
    changed = client.post(
        "/api/chat", json={"session_id": first["session_id"], "text": "Тестовый Гость", "request_id": "operation"}
    ).json()
    assert changed["kind"] == "error"
    assert service.sessions[first["session_id"]][0].lead.step == "name"


def test_old_replayed_prompt_keeps_its_original_token_and_cannot_submit_next_step(client, service):
    result = client.post("/api/chat", json={"text": MANAGER}).json()
    sid = result["session_id"]
    name_body = {
        "session_id": sid,
        "request_id": "name",
        "text": "Тестовый Гость",
        "form_token": result["form_token"],
    }
    name = client.post("/api/chat", json=name_body).json()
    summary = client.post(
        "/api/chat", json={"session_id": sid, "text": "+70000000000", "form_token": name["form_token"]}
    ).json()
    assert client.post("/api/chat", json=name_body).json() == name
    stale = client.post(
        "/api/chat", json={"session_id": sid, "text": "+70000000000", "form_token": name["form_token"]}
    ).json()
    assert stale == summary and service.sessions[sid][0].lead.step == "summary"
    assert not service.store.leads


def test_question_retry_does_not_charge_twice_and_cache_is_bounded(service):
    s = service.session(None, "widget")

    async def scenario():
        first = await service.ask(s, "v", "Сколько стоит доставка?", "question")
        assert (await service.ask(s, "v", "Сколько стоит доставка?", "question")) is first
        assert service.store.messages_today("v") == 1
        for index in range(40):
            await service.ask(s, "v", "", f"greeting-{index}")

    asyncio.run(scenario())
    assert len(s.requests) == 32
    service.forget(s.id)
    assert not s.requests and s.form_reply is None


@pytest.mark.parametrize("cancel_times", [1, 2])
def test_cancelled_completed_model_is_accounted_and_retry_reuses_reply(service, cancel_times):
    entered, release = threading.Event(), threading.Event()

    class Model:
        name = "test"
        calls = 0

        def complete(self, system, messages):
            self.calls += 1
            entered.set()
            assert release.wait(10)
            return Completion("Доставка по городу — 250 рублей. [1]", 123)

    service.consultant.llm = model = Model()
    s = service.session(None, "widget")

    async def scenario():
        pending = asyncio.create_task(service.ask(s, "v", "Сколько стоит доставка?", "question"))
        assert await asyncio.to_thread(entered.wait, 5)
        for _ in range(cancel_times):
            pending.cancel()
            await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert service.store.tokens_today() == 123
        assert service.store.messages_today("v") == 1
        assert (await service.ask(s, "v", "Сколько стоит доставка?", "question")).kind == "answer"

    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert model.calls == 1 and len(s.history) == 2
    assert service._waiting == 0 and not s.operation.locked()


def test_cancellation_while_queued_refunds_unstarted_work(service):
    from tests.conftest import FakeLLM

    service.consultant.llm = FakeLLM()
    s = service.session(None, "widget")

    async def scenario():
        await service._sem.acquire()
        pending = asyncio.create_task(service.ask(s, "v", "Сколько стоит доставка?", "question"))
        while service._waiting == 0:
            await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        service._sem.release()

    asyncio.run(scenario())
    assert not service.consultant.llm.calls and not s.requests
    assert service.store.messages_today("v") == service.store.tokens_today() == 0


def test_repeated_telegram_message_does_not_advance_form(service, monkeypatch):
    from app import bot

    monkeypatch.setattr(bot, "SERVICE", service)
    s = service.session("tg17", "telegram")
    message = SimpleNamespace(
        chat=SimpleNamespace(id=17),
        from_user=SimpleNamespace(id=17),
        message_id=42,
        text=MANAGER,
        answer=AsyncMock(),
    )

    async def scenario():
        await bot.text(message)
        await bot.text(message)

    asyncio.run(scenario())
    assert s.lead.step == "name" and not s.lead.name
