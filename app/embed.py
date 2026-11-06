"""Text embeddings on the local multilingual-e5-small model (int8 ONNX, 384 numbers).

No API and no GPU: the model runs on the CPU in about 10 ms per question. transformers.js runs
the same file in the browser with the same steps: the "query: " / "passage: " prefix the model
was trained with, mean pooling over real tokens, then normalization, so cosine similarity is a
plain dot product.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

DIM = 384
MAX_TOKENS = 512
BATCH = 8  # fragments per run when the base is indexed: padding to the longest one costs memory


class Embedder(Protocol):
    def embed(self, texts: list[str], kind: str) -> np.ndarray:
        """kind is "query" for questions and "passage" for fragments of the base."""


class E5Embedder:
    def __init__(self, model_dir: str | Path):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir = Path(model_dir)
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.enable_padding()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        # Without the arena the memory of a run goes back after it: the process stays at the
        # size of the model instead of the largest batch it has seen
        opts.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(
            str(model_dir / "onnx" / "model_quantized.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self.inputs = {i.name for i in self.session.get_inputs()}

    def embed(self, texts: list[str], kind: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        if len(texts) > BATCH:
            return np.concatenate([self.embed(texts[i : i + BATCH], kind) for i in range(0, len(texts), BATCH)])
        enc = self.tokenizer.encode_batch([f"{kind}: {t}" for t in texts])
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self.session.run(None, feed)[0]
        m = mask[..., None].astype(np.float32)
        vec = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        return (vec / np.linalg.norm(vec, axis=1, keepdims=True)).astype(np.float32)
