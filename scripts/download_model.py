"""Download the embedding model (multilingual-e5-small, int8 ONNX) into models/.

The same files run on the server (onnxruntime) and in the browser (transformers.js), so the
widget's offline mode and the API find exactly the same fragments.

    python scripts/download_model.py
"""

import sys
import urllib.request
from pathlib import Path

REPO = "Xenova/multilingual-e5-small"
FILES = ["config.json", "tokenizer.json", "tokenizer_config.json", "onnx/model_quantized.onnx"]
ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "models" / "multilingual-e5-small"


def main() -> int:
    for name in FILES:
        target = DEST / name
        if target.exists() and target.stat().st_size > 0:
            print(f"ok   {name}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/{REPO}/resolve/main/{name}"
        print(f"get  {name}")
        tmp = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
