import asyncio
import sys

import httpx
import pytest

from app import config
from app.api import app
from tests.test_uploads import tiny_pdf


def test_pdf_upload_uses_real_worker_and_preserves_previous_file_on_failure(client):
    uploaded = client.post("/api/upload", files={"file": ("terms.pdf", tiny_pdf("Delivery is free"))})
    assert uploaded.status_code == 200
    assert uploaded.json()["upload"] == "terms.pdf"
    sid = uploaded.json()["session_id"]
    bad = client.post("/api/upload", data={"session_id": sid}, files={"file": ("broken.pdf", b"not a pdf")})
    assert bad.status_code == 400 and bad.json()["upload"] == "terms.pdf"
    answer = client.post("/api/chat", json={"session_id": sid, "text": "Delivery is free"}).json()
    assert answer["kind"] == "answer" and answer["sources"][0]["source"] == "terms.pdf"


@pytest.mark.parametrize("cancel", [False, True])
def test_slow_pdf_keeps_health_responsive_bounds_queue_and_reaps_child(service, monkeypatch, cancel):
    from app import pdf

    monkeypatch.setattr(config, "PDF_TIMEOUT", 0.5)
    monkeypatch.setattr(config, "PDF_QUEUE_MAX", 0)
    real_spawn = asyncio.create_subprocess_exec
    processes = []
    app.state.service = service

    async def scenario():
        spawned = asyncio.Event()

        async def slow_spawn(*args, **kwargs):
            # A real child that cannot finish before the deadline, without a slow test PDF.
            proc = await real_spawn(sys.executable, "-c", "import time; time.sleep(30)", **kwargs)
            processes.append(proc)
            spawned.set()
            return proc

        monkeypatch.setattr(pdf.asyncio, "create_subprocess_exec", slow_spawn)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            session = service.session(None, "widget")
            await service.upload(session, "previous.txt", b"A previous document.")
            pending = asyncio.create_task(service.upload(session, "slow.pdf", tiny_pdf("test")))
            await asyncio.wait_for(spawned.wait(), 5)
            # A separate request completes while PDF extraction is still in progress.
            assert (await asyncio.wait_for(client.get("/health"), 0.3)).status_code == 200
            assert not pending.done()
            other = service.session(None, "widget")
            full = await service.upload(other, "other.pdf", tiny_pdf("test"))
            assert full.kind == "error" and "другие PDF" in full.text
            assert len(processes) == 1
            if cancel:
                pending.cancel()
                await asyncio.sleep(0)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                reply = await pending
                assert reply.kind == "error" and "слишком сложный" in reply.text
            assert processes[0].returncode is not None
            assert session.upload == "previous.txt"
            assert service._pdf_waiting == 0
            # The released slot can accept another PDF; expiration/deletion can finish too.
            monkeypatch.setattr(pdf.asyncio, "create_subprocess_exec", real_spawn)
            monkeypatch.setattr(config, "PDF_TIMEOUT", 5)
            assert (await service.upload(other, "valid.pdf", tiny_pdf("Delivery is free"))).kind == "upload"
            await service.delete(session.id)
            assert not service.consultant.searcher.chunks([f"upload:{session.id}"])

    try:
        asyncio.run(scenario())
    finally:
        del app.state.service
