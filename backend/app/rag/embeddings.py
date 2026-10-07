"""Embedding abstraction. The RAG layer depends only on ``Embedder``."""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from typing import Protocol

from app.config import ConfigurationError, Settings

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic feature-hashing embedder (unigrams + bigrams, signed, L2-normalised).

    A real, dependency-free embedding: it captures lexical overlap, NOT deep semantics. Use it for
    development, CI and offline demos; use ``sentence_transformers`` in production for semantic recall.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = f"hash-{dim}"

    def _vec(self, text: str) -> list[float]:
        tokens = _TOKEN.findall(text.lower())
        feats = tokens + [f"{a}_{b}" for a, b in itertools.pairwise(tokens)]
        v = [0.0] * self.dim
        for f in feats:
            h = int.from_bytes(hashlib.md5(f.encode(), usedforsecurity=False).digest()[:8], "big")
            v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ConfigurationError(
                "EMBEDDING_PROVIDER=sentence_transformers requires the ML extras: pip install -r requirements-ml.txt"
            ) from exc
        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension() or 0)
        self.name = f"st-{model_name}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.encode(texts, normalize_embeddings=True)]


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "sentence_transformers":
        emb = SentenceTransformerEmbedder(settings.embedding_model)
        if emb.dim != settings.embedding_dim:
            raise ConfigurationError(f"EMBEDDING_DIM={settings.embedding_dim} but model produces {emb.dim}-dim vectors; set EMBEDDING_DIM={emb.dim}.")
        return emb
    return HashEmbedder(settings.embedding_dim)
