"""Model providers behind one interface. The engine only calls complete(); switching GigaChat for
an OpenAI-compatible API (OpenRouter, Groq, YandexGPT, Ollama) is a change in .env.

Mind the licence of the key: the GigaChat freemium for individuals is for personal
non-commercial use only. A client's consultant needs a paid package or a company contract.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx

from . import config

UNKNOWN = "НЕ_ЗНАЮ"

SYSTEM = (
    "Ты консультант компании «{company}». Отвечай по-русски, коротко, 1–3 предложения, только по "
    "фрагментам базы знаний ниже. Цены, сроки и условия бери из фрагментов дословно, ничего не "
    "добавляй от себя. Если во фрагментах нет ответа на вопрос, ответь ровно одним словом: "
    f"{UNKNOWN}. Не обещай того, чего нет во фрагментах.\n\nФрагменты:\n{{fragments}}"
)


@dataclass
class Completion:
    text: str
    tokens: int


class LLM(Protocol):
    name: str

    def complete(self, system: str, messages: list[dict]) -> Completion: ...


class LLMError(RuntimeError):
    pass


class GigaChat:
    """GigaChat REST API: an OAuth token for 30 minutes, then OpenAI-like chat/completions."""

    name = "gigachat"
    OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    CHAT = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    def __init__(self, auth_key: str, scope: str, model: str, ca_bundle: str = "", timeout: float = 60):
        if not auth_key:
            raise LLMError("GIGACHAT_AUTH_KEY is empty")
        self.auth_key, self.scope, self.model = auth_key, scope, model
        self.http = httpx.Client(verify=ca_bundle or True, timeout=timeout)
        self._token, self._expires = "", 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        r = self.http.post(
            self.OAUTH,
            headers={"Authorization": f"Basic {self.auth_key}", "RqUID": str(uuid.uuid4())},
            data={"scope": self.scope},
        )
        if r.status_code != 200:
            raise LLMError(f"GigaChat OAuth {r.status_code}: {r.text[:200]}")
        data = r.json()
        self._token, self._expires = data["access_token"], data["expires_at"] / 1000
        return self._token

    def complete(self, system: str, messages: list[dict]) -> Completion:
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages], "temperature": 0.1}
        r = self.http.post(self.CHAT, headers={"Authorization": f"Bearer {self._access_token()}"}, json=body)
        if r.status_code != 200:
            raise LLMError(f"GigaChat {r.status_code}: {r.text[:200]}")
        data = r.json()
        return Completion(
            data["choices"][0]["message"]["content"].strip(), data.get("usage", {}).get("total_tokens", 0)
        )


class OpenAICompatible:
    name = "openai"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60):
        if not model:
            raise LLMError("OPENAI_MODEL is empty")
        self.model = model
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}
        )

    def complete(self, system: str, messages: list[dict]) -> Completion:
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages], "temperature": 0.1}
        r = self.http.post("/chat/completions", json=body)
        if r.status_code != 200:
            raise LLMError(f"{self.model} {r.status_code}: {r.text[:200]}")
        data = r.json()
        return Completion(
            data["choices"][0]["message"]["content"].strip(), data.get("usage", {}).get("total_tokens", 0)
        )


def from_config() -> LLM | None:
    if config.LLM_PROVIDER == "gigachat":
        return GigaChat(
            config.GIGACHAT_AUTH_KEY,
            config.GIGACHAT_SCOPE,
            config.GIGACHAT_MODEL,
            config.GIGACHAT_CA_BUNDLE,
            config.LLM_TIMEOUT,
        )
    if config.LLM_PROVIDER == "openai":
        return OpenAICompatible(config.OPENAI_BASE_URL, config.OPENAI_API_KEY, config.OPENAI_MODEL, config.LLM_TIMEOUT)
    if config.LLM_PROVIDER in ("", "none"):
        return None
    raise LLMError(f"unknown LLM_PROVIDER {config.LLM_PROVIDER!r}")


def fragments_block(hits) -> str:
    return "\n\n".join(f"[{i}] {h.chunk.title}\n{h.chunk.text}" for i, h in enumerate(hits, 1))
