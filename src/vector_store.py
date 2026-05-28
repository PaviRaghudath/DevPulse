"""
VectorStore — ChromaDB wrapper with persistent storage and collection-per-document design.

Each loaded file gets its own ChromaDB collection named after the file stem.
This allows per-document operations (list, clear) without affecting others.
"""
import re
from pathlib import Path

from src.config import VECTOR_STORE_PATH
from src.exceptions import CollectionNotFoundError

_UPSERT_BATCH = 500   # ChromaDB performs best with batches <= 500


class VectorStore:
    def __init__(self, persist_dir: str = VECTOR_STORE_PATH):
        self.persist_dir = persist_dir
        self._client = None     # lazy
        self._collection = None

    # ── Client ────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            try:
                import chromadb
            except ImportError:
                raise ImportError(
                    "chromadb is not installed. Run: pip install chromadb"
                )
            Path(self.persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self.persist_dir)
        return self._client

    # ── Collection management ─────────────────────────────────────────────

    def get_or_create_collection(self, name: str) -> None:
        safe_name = self._safe_name(name)
        client = self._get_client()
        self._collection = client.get_or_create_collection(
            name=safe_name,
            metadata={"hnsw:space": "cosine"},
        )

    def collection_exists(self, name: str) -> bool:
        """Return True if the collection already has documents indexed."""
        safe_name = self._safe_name(name)
        client = self._get_client()
        try:
            col = client.get_collection(safe_name)
            return col.count() > 0
        except Exception:
            return False

    def list_collections(self) -> list[str]:
        """Return names of all existing collections."""
        client = self._get_client()
        return [c.name for c in client.list_collections()]

    def delete_collection(self, name: str) -> None:
        """Delete a collection by document name."""
        safe_name = self._safe_name(name)
        client = self._get_client()
        try:
            client.delete_collection(safe_name)
        except Exception as e:
            raise CollectionNotFoundError(
                f"Collection '{safe_name}' not found: {e}"
            ) from e

    def collection_count(self, name: str) -> int:
        """Return number of chunks in a collection."""
        safe_name = self._safe_name(name)
        client = self._get_client()
        try:
            return client.get_collection(safe_name).count()
        except Exception:
            return 0

    # ── Data operations ───────────────────────────────────────────────────

    def add_chunks(
        self,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """Batch upsert chunks + embeddings into the current collection."""
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
        """
        Return the first n chunks from the current collection without needing
        a query embedding. Used by DocumentAnalyzer for initial text sampling.
        """
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

    def search(
        self, query_embedding: list[float], top_k: int = 6
    ) -> list[dict]:
        """
        Return top-k most similar chunks as list of:
            {"text": str, "metadata": dict, "distance": float}
        """
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
            {
                "text": doc,
                "metadata": meta,
                "distance": dist,
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _safe_name(name: str) -> str:
        """Convert a file stem to a valid ChromaDB collection name."""
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        safe = safe.strip("_-")
        # ChromaDB: 3–63 chars
        if len(safe) < 3:
            safe = (safe + "___")[:3]
        return safe[:63]
