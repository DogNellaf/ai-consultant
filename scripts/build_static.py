"""Build the browser mode as a static folder that any web server can host.

    python scripts/build_static.py dist/

dist/ gets the demo bakery site from widget/ (its pages and site/) with the widget switched to the
browser mode; Build/ holds what does not change
between releases: transformers.js, the onnxruntime-web WebAssembly and the e5 model, each with a
ready .gz next to it for nginx gzip_static (163 MB on disk, about 92 MB over the wire).

The page needs a CSP with 'wasm-unsafe-eval' and worker-src 'self' blob:, and nothing outside
its own origin: no CDN, no Hugging Face.
"""

from __future__ import annotations

import gzip
import io
import re
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TRANSFORMERS = "4.3.1"
ORT = "1.31.0-dev.20260914-8d85527a0"  # the onnxruntime-web build transformers.js 4.3.1 is made for
ORT_FILES = ["ort-wasm-simd-threaded.asyncify.mjs", "ort-wasm-simd-threaded.asyncify.wasm"]
CACHE = ROOT / "models" / "npm"
MODEL = ROOT / "models" / "multilingual-e5-small"
MODEL_FILES = ["config.json", "tokenizer.json", "tokenizer_config.json", "onnx/model_quantized.onnx"]
GZIP = (".wasm", ".mjs", ".js", ".onnx", ".json")

PAGES = ["index.html", "about.html", "products.html", "store.html", "credits.html"]
WIDGET_TAG = re.compile(r'<script src="widget\.js"([^>]*?) defer></script>')
BROWSER_TAG = (
    '<script src="kb-search.js"></script>\n'
    r'<script src="widget.js"\1 data-mode="browser" data-index="kb-index.json" data-model-path="Build/"'
    "\n"
    '  data-wasm-path="Build/transformers-{tv}/" data-transformers="Build/transformers-{tv}/transformers.min.js" defer></script>'
)


def npm_file(package: str, version: str, inner: str) -> bytes:
    tgz = CACHE / f"{package.replace('/', '-')}-{version}.tgz"
    if not tgz.exists():
        tgz.parent.mkdir(parents=True, exist_ok=True)
        name = package.split("/")[-1]
        urllib.request.urlretrieve(f"https://registry.npmjs.org/{package}/-/{name}-{version}.tgz", tgz)
    with tarfile.open(tgz) as tar:
        return tar.extractfile(f"package/{inner}").read()


def main(out: str) -> int:
    from scripts.export_index import main as export_index

    dist = Path(out)
    if dist.exists():
        shutil.rmtree(dist)
    build = dist / "Build"
    tdir = build / f"transformers-{TRANSFORMERS}"
    tdir.mkdir(parents=True)

    for name in ("widget.js", "widget.css", "kb-search.js"):
        shutil.copy(ROOT / "widget" / name, dist / name)
    shutil.copytree(ROOT / "widget" / "site", dist / "site")
    export_index(str(dist / "kb-index.json"))
    tag = BROWSER_TAG.replace("{tv}", TRANSFORMERS)
    for name in PAGES:
        html, n = WIDGET_TAG.subn(tag, (ROOT / "widget" / name).read_text(encoding="utf-8"))
        assert n == 1, f"{name}: no widget tag"
        (dist / name).write_text(html, encoding="utf-8")

    (tdir / "transformers.min.js").write_bytes(
        npm_file("@huggingface/transformers", TRANSFORMERS, "dist/transformers.min.js")
    )
    for name in ORT_FILES:
        (tdir / name).write_bytes(npm_file("onnxruntime-web", ORT, f"dist/{name}"))
    for name in MODEL_FILES:
        target = build / "multilingual-e5-small" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(MODEL / name, target)

    raw = packed = 0
    for f in sorted(build.rglob("*")):
        if f.is_file() and f.suffix in GZIP:
            data = f.read_bytes()
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as gz:
                gz.write(data)
            f.with_name(f.name + ".gz").write_bytes(buf.getvalue())
            raw += len(data)
            packed += len(buf.getvalue())
    print(f"{dist}: Build/ {raw / 1e6:.0f} MB, gzip {packed / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dist"))
