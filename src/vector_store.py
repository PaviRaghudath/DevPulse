"""
VectorStore — ChromaDB wrapper with persistent storage and collection-per-document design.

Falls back to a numpy in-memory store when chromadb is unavailable (e.g. Streamlit Cloud).

Each loaded file gets its own collection named after the file stem.
"""
import re
from pathlib import Path

from src.config import VECTOR_STORE_PATH
from src.exceptions import CollectionNotFoundError

_UPSERT_BATCH = 500

# Detect chromadb availability once at import time
try:
    import chromadb as _chromadb
    _CHROMADB_OK = True
except Exception:
    _chromadb = None
    _CHROMADB_OK = False


# ── In-memory fallback (numpy cosine similarity) ───────────────────────────

class _MemoryCollection:
    """Minimal ChromaDB-compatible collection backed by plain Python lists."""

    def __init__(self, name: str):
        self.name = name
        self._ids:        list[str]        = []
        self._docs:       list[str]        = []
        self._embeddings: list[list[float]]= []
        self._metas:      list[dict]       = []

    def count(self) -> int:
        return len(self._ids)

    def upsert(self, ids, documents, embeddings, metadatas):
        for id_, doc, emb, meta in zip(ids, documents, embeddings, metadatas):
            if id_ in self._ids:
                idx = self._ids.index(id_)
                self._docs[idx]       = doc
                self._embeddings[idx] = emb
                self._metas[idx]      = meta
            else:
                self._ids.append(id_)
                self._docs.append(doc)
                self._embeddings.append(emb)
                self._metas.append(meta)

    def get(self, limit=40, include=None):
        n = min(limit, len(self._docs))
        return {"documents": self._docs[:n], "metadatas": self._metas[:n]}

    def query(self, query_embeddings, n_results=6, include=None):
        import numpy as np
        q = np.array(query_embeddings[0], dtype=float)
        q_norm = q / (np.linalg.norm(q) + 1e-10)
        mat = np.array(self._embeddings, dtype=float)
        norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-10
        sims = mat / norms @ q_norm
        top = int(min(n_results, len(self._ids)))
        idxs = np.argsort(-sims)[:top]
        return {
            "documents": [[self._docs[i] for i in idxs]],
            "metadatas": [[self._metas[i] for i in idxs]],
            "distances": [[float(1 - sims[i]) for i in idxs]],
        }


class _MemoryClient:
    """Minimal ChromaDB-compatible client using _MemoryCollection."""

    def __init__(self):
        self._cols: dict[str, _MemoryCollection] = {}

    def get_or_create_collection(self, name, metadata=None):
        if name not in self._cols:
            self._cols[name] = _MemoryCollection(name)
        return self._cols[name]

    def get_collection(self, name):
        if name not in self._cols:
            raise ValueError(f"Collection '{name}' not found")
        return self._cols[name]

    def list_collections(self):
        return list(self._cols.values())

    def delete_collection(self, name):
        if name not in self._cols:
            raise ValueError(f"Collection '{name}' not found")
        del self._cols[name]


# ── VectorStore ────────────────────────────────────────────────────────────

class VectorStore:
    def __init__(self, persist_dir: str = VECTOR_STORE_PATH):
        self.persist_dir = persist_dir
        self._client = None
        self._collection = None

    # ── Client ────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            if _CHROMADB_OK:
                Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
                self._client = _chromadb.PersistentClient(path=self.persist_dir)
            else:
                self._client = _MemoryClient()
        return self._client

    @property
    def is_persistent(self) -> bool:
        return _CHROMADB_OK

    # ── Collection management ─────────────────────────────────────────────

    def get_or_create_collection(self, name: str) -> None:
        safe_name = self._safe_name(name)
        client = self._get_client()
        self._collection = client.get_or_create_collection(
            name=safe_name,
            metadata={"hnsw:space": "cosine"},
        )

    def collection_exists(self, name: str) -> bool:
        safe_name = self._safe_name(name)
        client = self._get_client()
        try:
            col = client.get_collection(safe_name)
            return col.count() > 0
        except Exception:
            return False

    def list_collections(self) -> list[str]:
        client = self._get_client()
        return [c.name for c in client.list_collections()]

    def delete_collection(self, name: str) -> None:
        safe_name = self._safe_name(name)
        client = self._get_client()
        try:
            client.delete_collection(safe_name)
        except Exception as e:
            raise CollectionNotFoundError(
                f"Collection '{safe_name}' not found: {e}"
            ) from e

    def collection_count(self, name: str) -> int:
        safe_name = self._safe_name(name)
        client = self._get_client()
        try:
            return client.get_collection(safe_name).count()
        except Exception:
            return 0

    # ── Data operations ───────────────────────────────────────────────────

    def add_chunks(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        if self._collection is None:
            raise RuntimeError("Call get_or_create_collection() first.")
        for i in range(0, len(chunks), _UPSERT_BATCH):
            batch_chunks = chunks[i : i + _UPSERT_BATCH]
            batch_embeddings = embeddings[i : i + _UPSERT_BATCH]
            self._collection.upsert(
                ids=[f"chunk_{c['metadata']['chunk_id']}" for c in batch_chunks],
                documents=[c["text"] for c in batch_chunks],
                embeddings=batch_embeddings,
                metadatas=[c["metadata"] for c in batch_chunks],
            )

    def get_sample(self, n: int = 40) -> list[dict]:
        if self._collection is None:
            return []
        count = self._collection.count()
        if count == 0:
            return []
        result = self._collection.get(
            limit=min(n, count),
            include=["documents", "metadatas"],
        )
        return [
            {"text": doc, "metadata": meta}
            for doc, meta in zip(result["documents"], result["metadatas"])
        ]

    def search(self, query_embedding: list[float], top_k: int = 6) -> list[dict]:
        if self._collection is None:
            raise RuntimeError("Call get_or_create_collection() first.")
        count = self._collection.count()
        if count == 0:
            return []
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, count),
            include=["documents", "metadatas", "distances"],
        )
        return [
            {"text": doc, "metadata": meta, "distance": dist}
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _safe_name(name: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        safe = safe.strip("_-")
        if len(safe) < 3:
            safe = (safe + "___")[:3]
        return safe[:63]
