"""Build the browser mode as a static folder that any web server can host.

    python scripts/build_static.py dist/

dist/index.html is the demo bakery page with the widget open; Build/ holds what does not change
between releases: transformers.js, the onnxruntime-web WebAssembly and the e5 model, each with a
ready .gz next to it for nginx gzip_static (163 MB on disk, about 92 MB over the wire).

The page needs a CSP with 'wasm-unsafe-eval' and worker-src 'self' blob:, and nothing outside
its own origin: no CDN, no Hugging Face.
"""

from __future__ import annotations

import gzip
import io
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

PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Пекарня «Колосок»</title>
<link rel="stylesheet" href="page.css">
</head>
<body>
<header class="kl-head"><div class="kl-logo">🥖 Колосок</div><nav><span>Хлеб</span><span>Выпечка</span><span>Торты</span><span>Доставка</span></nav></header>
<main class="kl-main">
  <h1>Хлеб на закваске, выпечка и торты на заказ</h1>
  <p>Вымышленная пекарня для демонстрации ИИ-консультанта. Справа внизу — виджет: спросите про цены,
  доставку или торты. Поиск идёт на вашем устройстве, вопросы никуда не отправляются.</p>
  <div class="kl-cards">
    <div><b>Батон на закваске</b><span>140 ₽</span></div>
    <div><b>Круассан сливочный</b><span>120 ₽</span></div>
    <div><b>Медовик</b><span>1 900 ₽/кг</span></div>
  </div>
</main>
<script src="kb-search.js"></script>
<script src="widget.js" data-title="Пекарня «Колосок»" data-mode="browser" data-open="1"
  data-index="kb-index.json" data-model-path="Build/" data-wasm-path="Build/transformers-{tv}/"
  data-transformers="Build/transformers-{tv}/transformers.min.js" defer></script>
</body>
</html>
"""


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

    for name in ("widget.js", "widget.css", "kb-search.js", "page.css"):
        shutil.copy(ROOT / "widget" / name, dist / name)
    export_index(str(dist / "kb-index.json"))
    (dist / "index.html").write_text(PAGE.replace("{tv}", TRANSFORMERS), encoding="utf-8")

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
