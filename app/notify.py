"""A lead goes to the manager's Telegram chat with the dialog that led to it."""

from __future__ import annotations

import html
import logging

import httpx

from . import config
from .store import Lead

log = logging.getLogger(__name__)
LIMIT = 4000  # Telegram allows 4096 characters per message


def lead_text(lead: Lead) -> str:
    channel = "виджет на сайте" if lead.channel == "widget" else "Telegram-бот"
    lines = [
        f"<b>Заявка №{lead.id}</b> · {channel}",
        f"Имя: {html.escape(lead.name)}",
        f"Телефон: {html.escape(lead.phone)}",
        f"Вопрос: {html.escape(lead.summary)}",
    ]
    dialog = [m for m in lead.history if m["content"]][-12:]
    if dialog:
        lines += ["", "<b>Переписка</b>"]
        for m in dialog:
            who = "Клиент" if m["role"] == "user" else "Бот"
            lines.append(f"{who}: {html.escape(m['content'][:400])}")
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
