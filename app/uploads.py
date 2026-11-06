"""A visitor's own document: .txt, .md or .pdf, small, kept for the session only."""

from __future__ import annotations

import io

from . import config
from .kb import Chunk, parse_plain


class UploadError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if len(data) > config.UPLOAD_MAX_BYTES:
        raise UploadError(f"Файл больше {config.UPLOAD_MAX_BYTES // 1000} КБ, пришлите поменьше.")
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) > config.UPLOAD_MAX_PAGES:
                raise UploadError(f"В PDF больше {config.UPLOAD_MAX_PAGES} страниц, пришлите покороче.")
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError as e:
            raise UploadError("Не получилось прочитать PDF.") from e
    elif name.endswith((".txt", ".md")):
        for enc in ("utf-8", "cp1251"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise UploadError("Не получилось прочитать текст, сохраните его в UTF-8.")
    else:
        raise UploadError("Подойдёт файл .txt, .md или .pdf.")
    text = text.strip()
    if not text:
        raise UploadError("В файле нет текста. Если это скан, его сначала нужно распознать.")
    return text[: config.UPLOAD_MAX_CHARS]


def to_chunks(filename: str, text: str, session_id: str) -> list[Chunk]:
    return parse_plain(text, filename, collection=f"upload:{session_id}")
