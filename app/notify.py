"""A lead goes to the manager's Telegram chat with the dialog that led to it."""

from __future__ import annotations

import html as _html
import logging

import httpx

from . import config
from .store import Lead

log = logging.getLogger(__name__)
LIMIT = 4000  # Telegram allows 4096 characters per message


def lead_text(lead: Lead, html: bool = True) -> str:
    """The Telegram message (HTML), or the same words as plain text for the demo preview."""
    esc = _html.escape if html else str
    bold = (lambda t: f"<b>{t}</b>") if html else str
    channel = "виджет на сайте" if lead.channel == "widget" else "Telegram-бот"
    lines = [
        f"{bold(f'Заявка №{lead.id}')} · {channel}",
        f"Имя: {esc(lead.name)}",
        f"Телефон: {esc(lead.phone)}",
        f"Вопрос: {esc(lead.summary)}",
    ]
    dialog = [m for m in lead.history if m["content"]][-12:]
    if dialog:
        lines += ["", bold("Переписка")]
        for m in dialog:
            who = "Клиент" if m["role"] == "user" else "Бот"
            lines.append(f"{who}: {esc(m['content'][:400])}")
    text = "\n".join(lines)
    return text if len(text) <= LIMIT else text[: LIMIT - 1] + "…"


def send_lead(lead: Lead) -> bool:
    if not (config.MANAGER_BOT_TOKEN and config.MANAGER_CHAT_ID):
        log.info("lead %s saved, MANAGER_CHAT_ID is not set", lead.id)
        return False
    r = httpx.post(
        f"https://api.telegram.org/bot{config.MANAGER_BOT_TOKEN}/sendMessage",
        json={"chat_id": config.MANAGER_CHAT_ID, "text": lead_text(lead), "parse_mode": "HTML"},
        proxy=config.TELEGRAM_PROXY or None,
        timeout=15,
    )
    if r.status_code != 200:
        log.warning("lead %s: Telegram %s %s", lead.id, r.status_code, r.text[:200])
        return False
    return True
