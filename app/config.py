"""Settings from the environment (.env next to docker-compose.yml). Everything has a default
that runs the demo base without keys: no model, answers straight from the fragments."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


COMPANY = os.getenv("COMPANY", "Пекарня «Колосок»")
KB_DIR = Path(os.getenv("KB_DIR", str(ROOT / "knowledge" / "kolosok")))

# Empty DATABASE_URL keeps everything in memory (tests, a quick look); Docker sets PostgreSQL.
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Model: "none" answers with the found fragment, "gigachat" or "openai" (any OpenAI-compatible API:
# OpenRouter, Groq, YandexGPT, a local Ollama) write the answer from the fragments.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none").lower()
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY", "")  # "Authorization key" from the Sber cabinet
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat-2")
# GigaChat's certificates chain to the Russian Trusted Root CA, which is not in the usual bundles:
# the repository carries it in certs/
_CA = ROOT / "certs" / "russian_trusted_ca.pem"
GIGACHAT_CA_BUNDLE = os.getenv("GIGACHAT_CA_BUNDLE", str(_CA) if _CA.exists() else "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")
LLM_TIMEOUT = _float("LLM_TIMEOUT", 60)

# Search (search.py). With a model the TOP_K_LLM best fragments go to it whenever the best one scores
# MIN_SCORE_LLM, and the model says when they have no answer. Without a model the best fragment is
# the answer when it has MIN_LEXICAL_ALONE of the question's words, or MIN_LEXICAL of them and
# MIN_GRAMS of its 4-grams.
TOP_K = _int("TOP_K", 3)
TOP_K_LLM = _int("TOP_K_LLM", 5)
MIN_SCORE_LLM = _float("MIN_SCORE_LLM", 0.25)
MIN_LEXICAL_ALONE = _float("MIN_LEXICAL_ALONE", 0.6)
MIN_LEXICAL = _float("MIN_LEXICAL", 0.4)
MIN_GRAMS = _float("MIN_GRAMS", 0.3)
SECOND_SOURCE_GAP = _float("SECOND_SOURCE_GAP", 0.03)

# Limits. GigaChat gives individuals one stream, so model calls go through a queue of one.
MESSAGES_PER_DAY = _int("MESSAGES_PER_DAY", 10)
DAILY_TOKEN_BUDGET = _int("DAILY_TOKEN_BUDGET", 200_000)
LLM_CONCURRENCY = _int("LLM_CONCURRENCY", 1)
QUEUE_MAX = _int("QUEUE_MAX", 20)
QUOTA_SALT = os.getenv("QUOTA_SALT", "change-me")

# Uploads: a small text or PDF to ask about, kept for the session only.
UPLOAD_MAX_BYTES = _int("UPLOAD_MAX_BYTES", 300_000)
UPLOAD_MAX_PAGES = _int("UPLOAD_MAX_PAGES", 20)
UPLOAD_MAX_CHARS = _int("UPLOAD_MAX_CHARS", 30_000)
SESSION_TTL = _int("SESSION_TTL", 3600)

# Telegram: the consultant bot and the chat where leads go.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MANAGER_BOT_TOKEN = os.getenv("MANAGER_BOT_TOKEN", "") or TELEGRAM_BOT_TOKEN
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID", "")
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", "")

ALLOWED_ORIGINS = _list("ALLOWED_ORIGINS", "*")

# A public demo: the lead form runs to the end, but the lead is neither saved nor sent, the
# visitor sees the message the manager would get instead. No names and phones of strangers kept.
DEMO_LEADS = os.getenv("DEMO_LEADS", "").lower() in ("1", "true", "yes")
