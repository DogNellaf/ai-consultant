"""Export the knowledge base for the widget's browser mode: fragments, their e5 vectors, the
search thresholds and the word list, so widget/kb-search.js scores exactly like app/search.py.

    python scripts/export_index.py widget/kb-index.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, lexical, search  # noqa: E402
from app.embed import E5Embedder  # noqa: E402
from app.kb import load_dir  # noqa: E402


def main(out: str) -> int:
    chunks = load_dir(config.KB_DIR)
    vectors = E5Embedder(config.MODEL_DIR).embed([c.passage for c in chunks], "passage")
    data = {
        "company": config.COMPANY,
        "model": "multilingual-e5-small",
        "search": {
            "candidates": search.CANDIDATES,
            "lexical_weight": search.LEXICAL_WEIGHT,
            "top_k": config.TOP_K,
            "min_dense": config.MIN_DENSE,
            "min_lexical": config.MIN_LEXICAL,
            "second_source_gap": config.SECOND_SOURCE_GAP,
        },
        "lexical": {"stem": lexical.STEM, "min_match": lexical.MIN_MATCH, "stopwords": sorted(lexical.STOPWORDS)},
        "chunks": [
            {"id": c.id, "source": c.source, "title": c.title, "text": c.text, "vec": [round(float(x), 5) for x in v]}
            for c, v in zip(chunks, vectors, strict=True)
        ],
    }
    Path(out).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{out}: {len(chunks)} fragments")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "widget/kb-index.json"))
