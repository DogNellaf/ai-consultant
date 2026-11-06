"""HTTP API for the site widget, plus the widget files and a demo page of the made-up bakery.

uvicorn app.api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .service import Service, visitor_key

WIDGET = Path(__file__).resolve().parent.parent / "widget"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "service"):
        from .setup import build

        app.state.service = build()
    yield


app = FastAPI(title="ai-consultant", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Content-Type"]
)


class Ask(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    text: str = Field(default="", max_length=1000)


def _service(request: Request) -> Service:
    return request.app.state.service


def _visitor(request: Request) -> str:
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "")
    return visitor_key(f"ip:{ip}")


def _out(service: Service, s, visitor: str, reply) -> dict:
    return {"session_id": s.id, "remaining": service.remaining(visitor), "upload": s.upload, **reply.as_dict()}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/chat")
async def chat(body: Ask, request: Request):
    service = _service(request)
    s = service.session(body.session_id, "widget")
    visitor = _visitor(request)
    reply = await service.ask(s, visitor, body.text)
    return _out(service, s, visitor, reply)


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...), session_id: str = Form(default="")):
    service = _service(request)
    s = service.session(session_id or None, "widget")
    data = await file.read(config.UPLOAD_MAX_BYTES + 1)
    reply = await service.upload(s, file.filename or "file.txt", data)
    status = 400 if reply.kind == "error" else 200
    return JSONResponse(_out(service, s, _visitor(request), reply), status_code=status)


@app.post("/api/upload/delete")
async def upload_delete(body: Ask, request: Request):
    service = _service(request)
    s = service.session(body.session_id, "widget")
    return _out(service, s, _visitor(request), service.drop_upload(s))


# The model for the browser mode (browser.html) and the widget files with the demo pages.
if config.MODEL_DIR.exists():
    app.mount("/models/multilingual-e5-small", StaticFiles(directory=config.MODEL_DIR), name="models")
app.mount("/", StaticFiles(directory=WIDGET, html=True), name="widget")
