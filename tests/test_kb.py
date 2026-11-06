from app import config
from app.kb import load_dir, parse_markdown, parse_plain
from app.lexical import idf, overlap, stems


def test_sections_become_fragments_with_titles():
    chunks = parse_markdown("# Прайс\n\nВступление.\n\n## Хлеб\n\nБатон — 140 ₽.\nРжаной — 160 ₽.\n", "price.md")
    assert [c.title for c in chunks] == ["Прайс", "Прайс › Хлеб"]
    assert chunks[1].text == "Батон — 140 ₽. Ржаной — 160 ₽."
    assert chunks[1].passage.startswith("Прайс › Хлеб. ")


def test_long_section_is_cut_by_sentences():
    body = " ".join(f"Предложение номер {i} про хлеб." for i in range(80))
    chunks = parse_markdown(f"# Док\n\n## Раздел\n\n{body}\n", "doc.md")
    assert len(chunks) > 1
    assert all(len(c.text) <= 900 for c in chunks)


def test_plain_upload_without_headings():
    chunks = parse_plain("Первый абзац.\n\nВторой абзац.", "notes.txt", "upload:x")
    assert chunks[0].title == "notes"
    assert chunks[0].collection == "upload:x"


def test_demo_base_loads():
    chunks = load_dir(config.KB_DIR)
    titles = {c.title for c in chunks}
    assert "Доставка и оплата › Самовывоз" in titles
    assert len({c.id for c in chunks}) == len(chunks)


def test_stems_drop_stopwords_and_cut_words():
    assert stems("Сколько стоит доставка?") == ["стоит", "доста"]
    assert stems("Ёлка и елка") == ["елка"]


def test_rare_words_weigh_more():
    corpus = [stems("Доставка стоит 250"), stems("Торт стоит 1900"), stems("Медовик торт")]
    q = stems("сколько стоит медовик")
    w = idf(q, corpus)
    assert w["медов"] > w["стоит"]
    assert overlap(q, corpus[2], w) > overlap(q, corpus[0], w)


def test_short_prefix_is_not_a_match():
    q = stems("пост")
    assert overlap(q, stems("постные изделия"), idf(q, [])) == 1.0
    q = stems("кот")
    assert overlap(q, stems("котлета"), idf(q, [])) == 0.0
