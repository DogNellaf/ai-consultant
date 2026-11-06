"""Knowledge base: Markdown files cut into fragments by "## " sections.

A fragment is one section with the document and section titles in front ("Доставка и оплата ›
Самовывоз"), so a short question like "где забрать?" still meets the topic word. Long sections
are cut further by paragraphs so a fragment stays readable as an answer source.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_CHARS = 900


@dataclass
class Chunk:
    source: str  # file name, "price.md" or the uploaded file
    title: str  # "Прайс › Хлеб"
    text: str  # section text without the heading
    collection: str = "kb"  # "kb" or "upload:<session>"
    id: str = field(default="")

    def __post_init__(self):
        if not self.id:
            h = hashlib.sha1(f"{self.collection}|{self.source}|{self.title}|{self.text}".encode()).hexdigest()
            self.id = h[:16]

    @property
    def passage(self) -> str:
        """What the model embeds: titles plus the text."""
        return f"{self.title}. {self.text}"


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)  # lines inside a paragraph
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_long(text: str, limit: int = MAX_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for para in re.split(r"\n\n+|(?<=[.!?])\s+", text):
        if cur and len(cur) + len(para) + 1 > limit:
            parts.append(cur.strip())
            cur = ""
        cur += para + " "
    if cur.strip():
        parts.append(cur.strip())
    return parts


def parse_markdown(text: str, source: str, collection: str = "kb") -> list[Chunk]:
    doc_title = source.rsplit(".", 1)[0]
    sections: list[tuple[str, str]] = []
    head, body = "", []
    for line in text.splitlines():
        if line.startswith("# ") and not sections and not head:
            doc_title = line[2:].strip()
            continue
        if line.startswith("## "):
            if head or "".join(body).strip():
                sections.append((head, "\n".join(body)))
            head, body = line[3:].strip(), []
        else:
            body.append(line)
    sections.append((head, "\n".join(body)))

    chunks = []
    for head, body in sections:
        body = _clean(body)
        if not body:
            continue
        title = f"{doc_title} › {head}" if head else doc_title
        for part in _split_long(body):
            chunks.append(Chunk(source=source, title=title, text=part, collection=collection))
    return chunks


def parse_plain(text: str, source: str, collection: str) -> list[Chunk]:
    """An uploaded text without headings: fragments by paragraphs up to MAX_CHARS."""
    text = _clean(text)
    if text.lstrip().startswith("#") or "\n## " in text:
        return parse_markdown(text, source, collection)
    doc_title = source.rsplit(".", 1)[0]
    return [Chunk(source=source, title=doc_title, text=p, collection=collection) for p in _split_long(text)]


def load_dir(path: str | Path) -> list[Chunk]:
    chunks = []
    for f in sorted(Path(path).glob("*.md")):
        chunks += parse_markdown(f.read_text(encoding="utf-8"), f.name)
    return chunks
