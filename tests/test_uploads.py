import pytest

from app import config
from app.uploads import UploadError, extract_text


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF with a line of Latin text, enough for pypdf to extract."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def test_pdf_text():
    assert "Delivery is free" in extract_text("terms.pdf", tiny_pdf("Delivery is free"))


def test_txt_in_cp1251():
    assert extract_text("notes.txt", "Привет".encode("cp1251")) == "Привет"


@pytest.mark.parametrize(
    "name,data,message",
    [
        ("photo.jpg", b"x", ".pdf"),
        ("empty.txt", b"  ", "нет текста"),
        ("broken.pdf", b"not a pdf", "PDF"),
    ],
)
def test_rejected(name, data, message):
    with pytest.raises(UploadError, match=message):
        extract_text(name, data)


def test_too_big(monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_MAX_BYTES", 10)
    with pytest.raises(UploadError, match="КБ"):
        extract_text("a.txt", b"x" * 11)


def test_text_is_cut(monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_MAX_CHARS", 5)
    assert extract_text("a.txt", b"abcdefgh") == "abcde"
