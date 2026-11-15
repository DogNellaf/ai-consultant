"""One disposable parser process per PDF. Input/output use stdin/stdout only."""

from __future__ import annotations

import json
import math
import sys

from . import config
from .uploads import UploadError, extract_text


def main() -> None:
    config.UPLOAD_MAX_PAGES, config.UPLOAD_MAX_CHARS = map(int, sys.argv[1:3])
    memory, seconds = int(sys.argv[3]) * 1024 * 1024, math.ceil(float(sys.argv[4])) + 1
    try:
        import resource
    except ImportError:
        # Windows previews retain the parent's wall-clock deadline; production runs Linux.
        pass
    else:
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    try:
        data = sys.stdin.buffer.read(config.UPLOAD_MAX_BYTES + 1)
        result = {"text": extract_text("document.pdf", data)}
    except UploadError as exc:
        result = {"error": str(exc)}
    except MemoryError:
        result = {"error": "PDF требует слишком много памяти. Пришлите более простой файл."}
    except Exception:
        result = {"error": "Не получилось прочитать PDF."}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
