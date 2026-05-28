"""
IngestionPipeline — orchestrates: parse → chunk → embed → store.

Memory management for files up to 500MB:
1. Parsers yield segments lazily (never full file in RAM)
2. Chunker is a generator — no list accumulation
3. Chunks are buffered in EMBED_BUFFER_SIZE batches, embedded, written
   to ChromaDB, then the buffer is cleared and gc.collect() called
4. Peak RAM = model (~300MB) + embed buffer (~100KB text) + ChromaDB mmap
"""
import gc
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

from src.config import EMBED_BUFFER_SIZE
from src.chunker import DocumentChunker
from src.embeddings import EmbeddingEngine
from src.exceptions import UnsupportedFileTypeError
from src.parsers.pdf_parser import PdfParser
from src.parsers.docx_parser import DocxParser
from src.parsers.txt_parser import TxtParser
from src.parsers.csv_parser import CsvParser
from src.utils.file_utils import validate_file, collection_name_from_path
from src.utils import memory as mem
from src.vector_store import VectorStore


@dataclass
class IngestionResult:
    skipped: bool = False
    chunk_count: int = 0
    collection_name: str = ""
    duration_seconds: float = 0.0


class IngestionPipeline:
    def __init__(
        self,
        embedding_engine: EmbeddingEngine,
        vector_store: VectorStore,
        chunker: Optional[DocumentChunker] = None,
        embed_buffer_size: int = EMBED_BUFFER_SIZE,
    ):
        self.engine = embedding_engine
        self.store = vector_store
        self.chunker = chunker or DocumentChunker()
        self.embed_buffer_size = embed_buffer_size

        self._parsers = [PdfParser(), DocxParser(), TxtParser(), CsvParser()]

    # ── Public API ────────────────────────────────────────────────────────

    def ingest(
        self,
        file_path: str,
        force_reindex: bool = False,
        on_progress=None,
        collection_name: Optional[str] = None,
    ) -> IngestionResult:
        """
        Ingest a file into the vector store.

        Args:
            file_path: Path to the file (may be a temp path).
            force_reindex: If True, re-index even if already indexed.
            on_progress: Optional callable(chunks_done: int) for progress updates.
            collection_name: Override the collection name (use original filename stem
                             when file_path is a temp file).

        Returns:
            IngestionResult with stats.
        """
        path = validate_file(file_path)
        if collection_name is None:
            collection_name = collection_name_from_path(str(path))

        log.info(f"[Pipeline] Ingesting '{path.name}' → collection '{collection_name}'")

        if not force_reindex and self.store.collection_exists(collection_name):
            log.info(f"[Pipeline] Already indexed — skipping (use force_reindex=True to re-index)")
            return IngestionResult(skipped=True, collection_name=collection_name)

        self.store.get_or_create_collection(collection_name)
        log.info(f"[Pipeline] Collection ready: '{collection_name}'")

        parser = self._get_parser(str(path))
        log.info(f"[Pipeline] Parser: {parser.__class__.__name__}")

        start = time.time()
        total_chunks = 0
        buffer: list[dict] = []

        chunk_stream = self.chunker.chunk_stream(
            parser.parse(str(path)),
            source_file=str(path),
        )

        for chunk in chunk_stream:
            buffer.append(chunk)
            if len(buffer) >= self.embed_buffer_size:
                self._flush(buffer)
                total_chunks += len(buffer)
                log.info(f"[Pipeline] Flushed batch → total chunks so far: {total_chunks}")
                if on_progress:
                    on_progress(len(buffer))
                buffer = []
                mem.force_gc()

        if buffer:
            self._flush(buffer)
            total_chunks += len(buffer)
            log.info(f"[Pipeline] Final flush → total chunks: {total_chunks}")
            if on_progress:
                on_progress(len(buffer))

        # Verify what actually landed in ChromaDB
        stored_count = self.store.collection_count(collection_name)
        log.info(f"[Pipeline] Done. Chunks sent={total_chunks} | ChromaDB count={stored_count} | time={time.time()-start:.1f}s")

        return IngestionResult(
            skipped=False,
            chunk_count=total_chunks,
            collection_name=collection_name,
            duration_seconds=time.time() - start,
        )

    # ── Private ───────────────────────────────────────────────────────────

    def _flush(self, buffer: list[dict]) -> None:
        texts = [c["text"] for c in buffer]
        embeddings = self.engine.embed_batch(texts)
        self.store.add_chunks(buffer, embeddings)

    def _get_parser(self, file_path: str):
        ext = Path(file_path).suffix.lower()
        for parser in self._parsers:
            if parser.supports(ext):
                return parser
        raise UnsupportedFileTypeError(
            f"No parser found for extension '{ext}'"
        )
