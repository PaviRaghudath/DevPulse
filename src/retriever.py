"""
Retriever — combines EmbeddingEngine + VectorStore for end-to-end retrieval.
Builds a context string for Claude from the top-k retrieved chunks.
"""
import logging

from src.config import TOP_K_RETRIEVAL, MAX_CONTEXT_CHARS
from src.embeddings import EmbeddingEngine
from src.vector_store import VectorStore

log = logging.getLogger(__name__)


class Retriever:
    def __init__(
        self,
        embedding_engine: EmbeddingEngine,
        vector_store: VectorStore,
        top_k: int = TOP_K_RETRIEVAL,
    ):
        self.engine = embedding_engine
        self.store = vector_store
        self.top_k = top_k

    def retrieve(self, query: str) -> list[dict]:
        """Embed the query and return top-k similar chunks from the vector store."""
        log.info(f"[Retriever] Query: {query!r}")

        # Collection state
        col_name = self.store._collection.name if self.store._collection else "None"
        col_count = self.store._collection.count() if self.store._collection else 0
        log.info(f"[Retriever] Collection: '{col_name}' | Chunks in store: {col_count}")

        query_embedding = self.engine.embed_query(query)
        log.info(f"[Retriever] Query embedding generated (dim={len(query_embedding)})")

        results = self.store.search(query_embedding, top_k=self.top_k)
        log.info(f"[Retriever] Results returned: {len(results)}")
        for i, r in enumerate(results):
            log.info(f"[Retriever]   chunk[{i}] distance={r.get('distance', '?'):.4f} | text[:80]={r['text'][:80]!r}")

        return results

    def build_context(
        self, chunks: list[dict], max_chars: int = MAX_CONTEXT_CHARS
    ) -> str:
        """
        Concatenate retrieved chunks into a single context string for Claude.
        Chunks are separated by clear dividers. Truncates at max_chars.
        """
        parts: list[str] = []
        total = 0

        for i, chunk in enumerate(chunks):
            text = chunk["text"]
            header = f"[Excerpt {i + 1}]"
            block = f"{header}\n{text}"

            if total + len(block) > max_chars:
                remaining = max_chars - total
                if remaining > len(header) + 20:
                    parts.append(block[:remaining] + "…")
                break

            parts.append(block)
            total += len(block)

        return "\n\n---\n\n".join(parts)
