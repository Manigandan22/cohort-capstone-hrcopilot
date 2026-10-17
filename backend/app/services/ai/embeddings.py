"""Text embeddings for policy retrieval.

``fastembed`` runs an open-source ONNX model (default ``BAAI/bge-small-en-v1.5``) locally, so
no embedding API or GPU is needed. ``api`` calls an OpenAI-compatible embeddings endpoint
(e.g. Gemini) for small hosts where loading a local model would not fit in memory. ``hash`` is a dependency-free lexical fallback used for
offline tests and air-gapped environments; it is far weaker than a real embedding model.
"""

import hashlib
import re
import time
from functools import lru_cache
from typing import Protocol

import numpy as np

from app.core.config import settings


class Embedder(Protocol):
    # Identifies the model; the vector index is rebuilt when this changes.
    signature: str
    # Default minimum cosine similarity for a chunk to count as relevant.
    default_min_score: float

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


class FastEmbedEmbedder:
    default_min_score = 0.55

    def __init__(self, model_name: str, cache_dir: str):
        from fastembed import TextEmbedding  # Imported lazily: loading the model is slow.

        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self.signature = f"fastembed:{model_name}"

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.array(list(self._model.passage_embed(texts)), dtype=np.float32))

    def embed_query(self, text: str) -> np.ndarray:
        return _normalize(np.array(list(self._model.query_embed([text])), dtype=np.float32))[0]


class APIEmbedder:
    """Embeddings from an OpenAI-compatible API (e.g. Gemini ``gemini-embedding-001``).

    Uses almost no memory, which suits small free hosts (Render free tier: 512 MB).
    """

    BATCH = 32
    RATE_LIMIT_RETRIES = 4
    RATE_LIMIT_WAIT_SECONDS = 20

    def __init__(self, base_url: str, api_key: str, model: str, min_score: float):
        from openai import OpenAI  # The sync client is fine: embedding calls already run in a worker thread.

        self._client = OpenAI(base_url=base_url, api_key=api_key or "not-needed", timeout=60, max_retries=1)
        self._model = model
        self.signature = f"api:{base_url}:{model}"
        self.default_min_score = min_score

    def _embed(self, texts: list[str]) -> np.ndarray:
        from openai import RateLimitError

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            batch = texts[start : start + self.BATCH]
            # Free tiers count every text as a request (Gemini: 100/minute), so wait out 429s.
            for attempt in range(self.RATE_LIMIT_RETRIES + 1):
                try:
                    response = self._client.embeddings.create(model=self._model, input=batch)
                    break
                except RateLimitError:
                    if attempt == self.RATE_LIMIT_RETRIES:
                        raise
                    time.sleep(self.RATE_LIMIT_WAIT_SECONDS)
            # Results come back in input order (Gemini leaves ``index`` empty, so don't sort by it).
            vectors.extend(item.embedding for item in response.data)
        return _normalize(np.array(vectors, dtype=np.float32))

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        return self._embed(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text])[0]


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it many may me my of on or should the "
    "to what when where which who will with you your".split()
)


class HashingEmbedder:
    """Feature-hashed bag of words and bigrams. Deterministic and offline."""

    default_min_score = 0.12

    def __init__(self, dim: int = 4096):
        self._dim = dim
        self.signature = f"hash:{dim}"

    def _tokens(self, text: str) -> list[str]:
        words = [w.rstrip("s") if len(w) > 3 else w for w in _TOKEN_RE.findall(text.lower())]
        words = [w for w in words if w not in _STOPWORDS]
        return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]

    def _embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self._dim, dtype=np.float32)
        for token in self._tokens(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self._dim
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        return vector

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return _normalize(np.stack([self._embed(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


# Calibrated for gemini-embedding-001 on the seeded policy library (see docs/ai_architecture.md).
API_EMBEDDING_DEFAULT_MIN_SCORE = 0.6


@lru_cache
def get_embedder() -> Embedder:
    backend = settings.embedding_backend.strip().lower()
    if backend == "hash":
        return HashingEmbedder()
    if backend == "fastembed":
        return FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir)
    if backend == "api":
        return APIEmbedder(
            base_url=settings.embedding_base_url or settings.llm_base_url,
            api_key=settings.embedding_api_key or settings.llm_api_key,
            model=settings.embedding_model,
            min_score=API_EMBEDDING_DEFAULT_MIN_SCORE,
        )
    raise ValueError(f"Unknown EMBEDDING_BACKEND: {settings.embedding_backend}")
