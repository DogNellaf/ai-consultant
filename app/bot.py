"""Telegram bot on the same engine as the widget.

    python -m app.bot

Text goes to the consultant, a document (.txt, .md, .pdf) becomes the session's own base,
/search toggles the list of fragments the search looked at, /cancel stops the lead form.
"""

from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from . import config
from .engine import CANCEL, Reply
from .service import Service, visitor_key

log = logging.getLogger(__name__)
dp = Dispatcher()
SERVICE: Service | None = None
SHOW_SEARCH: set[int] = set()


def keyboard(buttons: list[str]):
    if not buttons:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=b)] for b in buttons], resize_keyboard=True)


def render(reply: Reply, show_search: bool) -> str:
    parts = [html.escape(reply.text)]
    if reply.sources:
        parts.append("\n".join(f"📄 <i>{html.escape(src['title'])}</i>" for src in reply.sources))
    if show_search and reply.search:
        rows = [
            f"{i}. {html.escape(h['title'])} — сходство {h['dense']:.3f}, слова {h['lexical']:.2f}"
            for i, h in enumerate(reply.search, 1)
        ]
        parts.append("<b>Как искался ответ</b>\n" + "\n".join(rows))
    return "\n\n".join(parts)


def _session(message: Message):
    return SERVICE.session(f"tg{message.chat.id}", "telegram")


async def send(message: Message, reply: Reply) -> None:
    await message.answer(
        render(reply, message.chat.id in SHOW_SEARCH), parse_mode="HTML", reply_markup=keyboard(reply.buttons)
    )


@dp.message(CommandStart())
async def start(message: Message):
    await send(message, SERVICE.consultant.greeting())


@dp.message(Command("search"))
async def toggle_search(message: Message):
    if message.chat.id in SHOW_SEARCH:
        SHOW_SEARCH.discard(message.chat.id)
        await message.answer("Найденные фрагменты больше не показываю.")
    else:
        SHOW_SEARCH.add(message.chat.id)
        await message.answer("Под ответом покажу все фрагменты, которые нашёл поиск, и их оценки.")


@dp.message(Command("cancel"))
async def cancel(message: Message):
    reply = await SERVICE.ask(_session(message), visitor_key(f"tg:{message.from_user.id}"), CANCEL)
    await send(message, reply)


@dp.message(F.document)
async def document(message: Message, bot: Bot):
    doc = message.document
    if doc.file_size and doc.file_size > config.UPLOAD_MAX_BYTES:
        await message.answer(f"Файл больше {config.UPLOAD_MAX_BYTES // 1000} КБ, пришлите поменьше.")
        return
    buf = await bot.download(doc)
    await send(message, await SERVICE.upload(_session(message), doc.file_name or "file.txt", buf.read()))


@dp.message(F.text)
async def text(message: Message):
    reply = await SERVICE.ask(_session(message), visitor_key(f"tg:{message.from_user.id}"), message.text)
    await send(message, reply)


async def main() -> None:
    global SERVICE
    from .setup import build

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty")
    SERVICE = build()
    session = AiohttpSession(proxy=config.TELEGRAM_PROXY) if config.TELEGRAM_PROXY else None
    bot = Bot(config.TELEGRAM_BOT_TOKEN, session=session)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
