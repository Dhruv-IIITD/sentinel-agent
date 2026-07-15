"""Embeddings for the vector retriever.

`HashingEmbedder` is deterministic and dependency-free (pure Python, no numpy),
so the vector pipeline runs and is testable offline. It is *lexical* (shared
tokens → similar vectors); for true semantic recall, swap in a real model via
`load_sentence_transformer()` (or an embeddings API) — the retriever and the DB
schema don't change, only the `Embedder`.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


def _tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9$]+", s.lower())


class HashingEmbedder:
    """Signed feature-hashing bag-of-words → L2-normalized fixed-dim vector."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokens(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    # Inputs are L2-normalized, so the dot product is the cosine similarity.
    return sum(x * y for x, y in zip(a, b))


def load_sentence_transformer(model_name: str = "all-MiniLM-L6-v2"):  # pragma: no cover
    """Optional real embedder (requires `sentence-transformers`)."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    class _ST:
        dim = model.get_sentence_embedding_dimension()

        def embed(self, text: str) -> list[float]:
            return model.encode(text, normalize_embeddings=True).tolist()

    return _ST()
