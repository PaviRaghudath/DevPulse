"""
EmbeddingEngine — wraps sentence-transformers with lazy loading and batched encoding.

The model (~80MB) is downloaded on first use and cached by sentence-transformers
in the HuggingFace cache directory (~/.cache/huggingface/).
"""
from src.config import EMBEDDING_MODEL, EMBEDDING_BATCH_SIZE
from src.exceptions import EmbeddingError


class EmbeddingEngine:
    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None  # lazy-loaded on first use

    # ── Public API ────────────────────────────────────────────────────────

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of text strings.
        Returns a list of float vectors (one per input text).
        Normalised to unit length for cosine similarity.
        """
        if not texts:
            return []
        try:
            model = self._load_model()
            embeddings = model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return embeddings.tolist()
        except Exception as e:
            raise EmbeddingError(f"Embedding failed: {e}") from e

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string and return its vector."""
        return self.embed_batch([query])[0]

    # ── Private ───────────────────────────────────────────────────────────

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise EmbeddingError(
                    "sentence-transformers is not installed. "
                    "Run: pip install sentence-transformers"
                )
            self._model = SentenceTransformer(self.model_name)
        return self._model
