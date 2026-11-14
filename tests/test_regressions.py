import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx
import pytest

from app import config
from app.api import app
from app.engine import DEMO_CONTACTS, KEEP, MANAGER
from app.llm import GigaChat, LLMError, OpenAICompatible
from tests.conftest import FakeLLM


def test_markdown_upload_can_answer_and_empty_replacement_keeps_file(service):
    from fastapi.testclient import TestClient

    app.state.service = service
    with TestClient(app) as client:
        r = client.post(
            "/api/upload",
            files={
                "file": (
                    "menu.md",
                    "## Тыквенный пирог\nСезонный пирог с тыквой продаётся только по пятницам. Цена пирога — 880 рублей.".encode(),
                )
            },
        ).json()
        assert r["kind"] == "upload" and "1 фрагмент." in r["text"]
        sid = r["session_id"]
        answer = client.post("/api/chat", json={"session_id": sid, "text": "Когда бывает пирог с тыквой?"}).json()
        assert answer["kind"] == "answer" and answer["sources"][0]["source"] == "menu.md"
        empty = client.post("/api/upload", data={"session_id": sid}, files={"file": ("empty.md", b"## Heading")})
        assert empty.status_code == 400 and empty.json()["upload"] == "menu.md"
        assert service.consultant.searcher.chunks([f"upload:{sid}"])
        assert client.post("/api/session/delete", json={"session_id": sid}).json() == {"ok": True}
        assert sid not in service.sessions
        assert service.consultant.searcher.chunks([f"upload:{sid}"]) == []
        assert client.post("/api/session/delete", json={"session_id": sid}).status_code == 200
    del app.state.service


@pytest.mark.parametrize("provider", ["gigachat", "openai"])
@pytest.mark.parametrize("failure", ["timeout", "connection", "json", "schema", "content"])
def test_provider_normalizes_transport_and_payload_errors(provider, failure):
    model = (
        GigaChat("test", "test", "test")
        if provider == "gigachat"
        else OpenAICompatible("https://model.invalid", "test", "test")
    )
    if provider == "gigachat":
        model._token, model._expires = "test", 1e12

    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("test timeout", request=request)
        if failure == "connection":
            raise httpx.ConnectError("test connection", request=request)
        if failure == "json":
            return httpx.Response(200, text="not JSON")
        if failure == "content":
            return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
        return httpx.Response(200, json={"choices": []})

    model.http.close()
    model.http = httpx.Client(base_url="https://model.invalid", transport=httpx.MockTransport(respond))
    with model.http, pytest.raises(LLMError):
        model.complete("system", [{"role": "user", "content": "question"}])


def test_network_failure_falls_back_through_api(service):
    from fastapi.testclient import TestClient

    service.consultant.llm = FakeLLM(error=httpx.ReadTimeout("timeout"))
    app.state.service = service
    with TestClient(app) as client:
        r = client.post("/api/chat", json={"text": "Можно забрать заказ самому?"}).json()
        assert r["kind"] == "answer" and r["mode"] == "fragments"
        assert r["decision"] == "provider_unavailable" and r["sources"]
    del app.state.service


def test_model_refusal_is_not_a_search_threshold_failure(consultant):
    from app.engine import Session

    consultant.llm = FakeLLM("НЕ_ЗНАЮ")
    reply = consultant.handle(Session("test", "widget"), "Сколько стоит доставка?")
    assert reply.kind == "unknown" and reply.decision == "model_refusal"
    assert reply.tokens > 0 and reply.search


def test_contact_form_is_excluded_from_next_model_context(service, monkeypatch):
    monkeypatch.setattr(config, "DEMO_LEADS", True)
    service.consultant.llm = FakeLLM()
    s = service.session(None, "widget")

    async def scenario():
        await service.ask(s, "v", "Сколько стоит доставка?")
        for text in (MANAGER, "ТестовоеИмя", "+7 000 000-00-00", KEEP):
            done = await service.ask(s, "v", text)
        assert "ТестовоеИмя" in done.manager_preview and "+70000000000" in done.manager_preview
        await service.ask(s, "v", "Можно забрать заказ самому?")

    asyncio.run(scenario())
    payload = str(service.consultant.llm.calls[-1])
    assert "ТестовоеИмя" not in payload and "70000000000" not in payload
    assert "ТестовоеИмя" not in str(s.history) and "70000000000" not in str(s.history)
    assert s.lead is None and service.store.leads == []


def test_demo_autofill_and_telegram_channel(client, monkeypatch):
    monkeypatch.setattr(config, "DEMO_LEADS", True)
    r = client.post("/api/chat", json={"channel": "telegram", "text": MANAGER}).json()
    assert DEMO_CONTACTS in r["buttons"]
    for text in (DEMO_CONTACTS, KEEP):
        r = client.post("/api/chat", json={"channel": "telegram", "session_id": r["session_id"], "text": text}).json()
    assert r["kind"] == "lead_done" and "Telegram" in r["manager_preview"]
    assert "+70000000000" in r["manager_preview"]


def test_concurrent_questions_reserve_one_remaining_slot(service, monkeypatch):
    monkeypatch.setattr(config, "MESSAGES_PER_DAY", 10)
    service.store.add_usage("v", 9, 0)
    service.consultant.llm = FakeLLM()

    async def scenario():
        return await asyncio.gather(
            *(service.ask(service.session(None, "widget"), "v", "Сколько стоит доставка?") for _ in range(3))
        )

    replies = asyncio.run(scenario())
    assert sorted(r.kind for r in replies) == ["answer", "limit", "limit"]
    assert service.store.messages_today("v") == 10


def test_reservation_is_atomic_across_threads(store):
    with ThreadPoolExecutor(max_workers=12) as pool:
        accepted = list(pool.map(lambda _: store.reserve_message("v", 10, date.today()), range(30)))
    assert sum(accepted) == 10 and store.messages_today("v") == 10


def test_queue_refusal_and_exception_release_reservation(service, monkeypatch):
    service.consultant.llm = FakeLLM()
    monkeypatch.setattr(config, "QUEUE_MAX", 0)
    assert asyncio.run(service.ask(service.session(None, "widget"), "v", "Сколько стоит доставка?")).kind == "busy"
    assert service.remaining("v") == config.MESSAGES_PER_DAY
    monkeypatch.setattr(config, "QUEUE_MAX", 20)
    service.consultant.llm = FakeLLM(error=RuntimeError("unexpected failure"))
    with pytest.raises(RuntimeError):
        asyncio.run(service.ask(service.session(None, "widget"), "v", "Сколько стоит доставка?"))
    assert service.remaining("v") == config.MESSAGES_PER_DAY


def test_budget_is_rechecked_after_waiting_for_model_slot(service, monkeypatch):
    monkeypatch.setattr(config, "DAILY_TOKEN_BUDGET", 100)
    service.consultant.llm = FakeLLM(tokens=120)

    async def scenario():
        return await asyncio.gather(
            *(service.ask(service.session(None, "widget"), str(i), "Можно забрать заказ самому?") for i in range(3))
        )

    replies = asyncio.run(scenario())
    assert [r.mode for r in replies] == ["fake", "fragments", "fragments"]
    assert len(service.consultant.llm.calls) == 1
