"""A small persistent vector store for policy chunks.

Chunks and their embeddings live in their own SQLite file (separate from the HRMS database),
and search is exact cosine similarity with NumPy. The policy library is a few hundred chunks
at most, so brute force is faster and simpler than running a vector database server.
"""

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class PolicyChunk:
    id: str
    policy_id: int
    title: str
    category: str
    filename: str | None
    chunk_index: int
    text: str


@dataclass(frozen=True)
class SearchHit:
    chunk: PolicyChunk
    score: float


class LocalVectorStore:
    def __init__(self, path: str, signature: str):
        """``signature`` identifies the embedding model; a different one wipes the index."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._cache: tuple[list[PolicyChunk], np.ndarray] | None = None
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS policy_versions (
                    policy_id INTEGER PRIMARY KEY,
                    version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    policy_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    filename TEXT,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_chunks_policy_id ON chunks (policy_id);
                """
            )
            row = self._conn.execute("SELECT value FROM meta WHERE key = 'signature'").fetchone()
            if row is None or row[0] != signature:
                self._conn.execute("DELETE FROM chunks")
                self._conn.execute("DELETE FROM policy_versions")
                self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('signature', ?)", (signature,))

    def policy_versions(self) -> dict[int, str]:
        with self._lock:
            return dict(self._conn.execute("SELECT policy_id, version FROM policy_versions").fetchall())

    def replace_policy(self, policy_id: int, version: str, chunks: list[PolicyChunk], embeddings: np.ndarray) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chunks WHERE policy_id = ?", (policy_id,))
            self._conn.executemany(
                "INSERT INTO chunks (id, policy_id, title, category, filename, chunk_index, text, embedding) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (c.id, c.policy_id, c.title, c.category, c.filename, c.chunk_index, c.text, e.astype(np.float32).tobytes())
                    for c, e in zip(chunks, embeddings)
                ],
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO policy_versions (policy_id, version) VALUES (?, ?)", (policy_id, version)
            )
            self._cache = None

    def delete_policies(self, policy_ids: list[int]) -> None:
        if not policy_ids:
            return
        with self._lock, self._conn:
            marks = ",".join("?" * len(policy_ids))
            self._conn.execute(f"DELETE FROM chunks WHERE policy_id IN ({marks})", policy_ids)
            self._conn.execute(f"DELETE FROM policy_versions WHERE policy_id IN ({marks})", policy_ids)
            self._cache = None

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def _load(self) -> tuple[list[PolicyChunk], np.ndarray]:
        with self._lock:
            if self._cache is None:
                rows = self._conn.execute(
                    "SELECT id, policy_id, title, category, filename, chunk_index, text, embedding FROM chunks ORDER BY id"
                ).fetchall()
                chunks = [PolicyChunk(*row[:7]) for row in rows]
                matrix = (
                    np.stack([np.frombuffer(row[7], dtype=np.float32) for row in rows])
                    if rows
                    else np.zeros((0, 0), dtype=np.float32)
                )
                self._cache = (chunks, matrix)
            return self._cache

    def search(self, query_vector: np.ndarray, top_k: int) -> list[SearchHit]:
        chunks, matrix = self._load()
        if not chunks:
            return []
        scores = matrix @ query_vector.astype(np.float32)
        order = np.argsort(-scores)[:top_k]
        return [SearchHit(chunk=chunks[i], score=float(scores[i])) for i in order]
