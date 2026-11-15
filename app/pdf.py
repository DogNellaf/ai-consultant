"""Bounded PDF extraction outside the HTTP worker; children never modify sessions."""

from __future__ import annotations

import asyncio
import json
import sys

from . import config
from .uploads import UploadError


async def extract_pdf(data: bytes) -> str:
    if len(data) > config.UPLOAD_MAX_BYTES:
        raise UploadError(f"Файл больше {config.UPLOAD_MAX_BYTES // 1000} КБ, пришлите поменьше.")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.pdf_worker",
        str(config.UPLOAD_MAX_PAGES),
        str(config.UPLOAD_MAX_CHARS),
        str(config.PDF_MEMORY_MB),
        str(config.PDF_TIMEOUT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    cancelled = False
    try:
        try:
            output, _ = await asyncio.wait_for(process.communicate(data), timeout=config.PDF_TIMEOUT)
        except TimeoutError as exc:
            raise UploadError("PDF слишком сложный для демо. Пришлите более простой PDF или текстовый файл.") from exc
        if process.returncode:
            raise UploadError("Не получилось обработать PDF в пределах лимитов. Пришлите более простой файл.")
        try:
            result = json.loads(output)
        except (ValueError, KeyError, TypeError) as exc:
            raise UploadError("Не получилось прочитать PDF.") from exc
        if not isinstance(result, dict):
            raise UploadError("Не получилось прочитать PDF.")
        if "error" in result:
            raise UploadError(str(result["error"]))
        if not isinstance(result.get("text"), str):
            raise UploadError("Не получилось прочитать PDF.")
        return result["text"]
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        # A cancelled request retains its slot/session lock until the child is reaped.
        reaped = asyncio.create_task(process.wait())
        while not reaped.done():
            try:
                await asyncio.shield(reaped)
            except asyncio.CancelledError:
                cancelled = True
        reaped.result()
        if cancelled:
            raise asyncio.CancelledError
