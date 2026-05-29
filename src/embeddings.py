"""
EmbeddingEngine — wraps sentence-transformers with lazy loading and batched encoding.

Falls back to OpenAI text-embedding-3-small when sentence-transformers / PyTorch
is unavailable (e.g. Streamlit Cloud free tier).

Priority:
  1. sentence-transformers (local, free, 384-dim)
  2. OpenAI text-embedding-3-small (API, 1536-dim) — requires OPENAI_API_KEY env var
"""
import os

from src.config import EMBEDDING_MODEL, EMBEDDING_BATCH_SIZE
from src.exceptions import EmbeddingError

# Detect available backend once at import time
try:
    from sentence_transformers import SentenceTransformer as _ST
    _ST_OK = True
except Exception:
    _ST = None
    _ST_OK = False


class EmbeddingEngine:
    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None      # sentence-transformers model (lazy)
        self._backend = None    # "local" | "openai"

    @property
    def backend(self) -> str:
        return self._backend or ("local" if _ST_OK else "openai")

    # ── Public API ────────────────────────────────────────────────────────

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            if _ST_OK:
                return self._embed_local(texts)
            return self._embed_openai(texts)
        except Exception as e:
            raise EmbeddingError(f"Embedding failed: {e}") from e

    def embed_query(self, query: str) -> list[float]:
        return self.embed_batch([query])[0]

    # ── Backends ──────────────────────────────────────────────────────────

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            self._model = _ST(self.model_name)
            self._backend = "local"
        embeddings = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        try:
            from openai import OpenAI
        except ImportError:
            raise EmbeddingError(
                "Neither sentence-transformers nor openai is available. "
                "Install one: pip install sentence-transformers  OR  pip install openai"
            )
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            # try st.secrets
            try:
                import streamlit as st
                api_key = st.secrets.get("OPENAI_API_KEY", "")
            except Exception:
                pass
        if not api_key:
            raise EmbeddingError(
                "sentence-transformers is unavailable and no OPENAI_API_KEY is set. "
                "Please enter your OpenAI API key in the sidebar."
            )
        self._backend = "openai"
        client = OpenAI(api_key=api_key)
        # OpenAI supports up to 2048 texts per request — batch to be safe
        all_embeddings = []
        for i in range(0, len(texts), 100):
            batch = texts[i : i + 100]
            resp = client.embeddings.create(
                model="text-embedding-3-small",
                input=batch,
            )
            all_embeddings.extend([d.embedding for d in resp.data])
        return all_embeddings
