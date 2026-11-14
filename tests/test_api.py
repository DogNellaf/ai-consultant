def test_chat_keeps_session_and_counts(client):
    r = client.post("/api/chat", json={"text": "Можно забрать заказ самому?"}).json()
    assert r["kind"] == "answer" and r["sources"][0]["source"] == "delivery.md"
    assert r["remaining"] == 9
    r2 = client.post("/api/chat", json={"session_id": r["session_id"], "text": "Позвать менеджера"}).json()
    assert r2["session_id"] == r["session_id"] and r2["kind"] == "lead"


def test_upload_and_delete(client):
    r = client.post("/api/upload", files={"file": ("menu.txt", "Пирог с тыквой по пятницам.".encode())}).json()
    assert r["kind"] == "upload" and r["upload"] == "menu.txt"
    d = client.post("/api/upload/delete", json={"session_id": r["session_id"]}).json()
    assert d["upload"] == ""


def test_bad_upload_is_400(client):
    r = client.post("/api/upload", files={"file": ("photo.jpg", b"x")})
    assert r.status_code == 400 and r.json()["kind"] == "error"


def test_widget_and_demo_page(client):
    assert client.get("/widget.js").status_code == 200
    assert client.get("/widget.css").status_code == 200
    assert "widget.js" in client.get("/").text
    assert client.get("/browser.html").status_code == 404  # the browser mode is gone with the model
    assert client.get("/health").json() == {"ok": True}


def test_site_pages_link_only_existing_files(client):
    """The bakery site in widget/: every page has the widget, every local link and asset exists."""
    import re
    from pathlib import Path

    widget = Path(__file__).resolve().parent.parent / "widget"
    for name in ("index.html", "products.html", "store.html", "about.html", "credits.html"):
        html = (widget / name).read_text(encoding="utf-8")
        assert client.get(f"/{name}").status_code == 200, name
        assert len(re.findall(r'<script src="widget\.js"', html)) == 1, name
        for ref in re.findall(r'(?:src|href)="([^"#:]+)"', html):
            assert (widget / ref).is_file(), f"{name}: {ref}"
    for css in (widget / "site" / "css").glob("*.css"):
        for ref in re.findall(r'url\("?([^")]+?)"?\)', css.read_text(encoding="utf-8")):
            if not ref.startswith("data:"):
                assert (css.parent / ref).resolve().is_file(), f"{css.name}: {ref}"
