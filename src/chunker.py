"""
DocumentChunker — splits parser output into fixed-size overlapping text chunks.

Strategy:
- Splits text on sentence/paragraph boundaries where possible, then by char limit.
- Maintains a carry-over buffer across segment boundaries so context is not lost
  at parser segment seams.
- Each chunk gets metadata: source file path and sequential chunk_id.
"""
import re
from typing import Generator

from src.config import CHUNK_SIZE, CHUNK_OVERLAP


class DocumentChunker:
    def __init__(self, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
        self.chunk_size = chunk_size
        self.overlap = overlap

    # ── Public API ────────────────────────────────────────────────────────

    def chunk_stream(
        self,
        segment_generator: Generator[str, None, None],
        source_file: str,
    ) -> Generator[dict, None, None]:
        """
        Consume a parser generator, yield chunk dicts lazily.
        A carry buffer preserves partial text across segment boundaries.
        """
        carry = ""
        chunk_index = 0

        for segment in segment_generator:
            combined = (carry + " " + segment).strip() if carry else segment
            chunks = self._split_to_chunks(combined)

            # Yield all but the last chunk (last may be incomplete)
            for chunk_text in chunks[:-1]:
                if chunk_text.strip():
                    yield self._make_chunk(chunk_text, source_file, chunk_index)
                    chunk_index += 1

            # Keep last chunk as carry (may grow with next segment)
            carry = chunks[-1] if chunks else ""

        # Flush remaining carry
        if carry.strip():
            yield self._make_chunk(carry, source_file, chunk_index)

    # ── Private helpers ───────────────────────────────────────────────────

    def _split_to_chunks(self, text: str) -> list[str]:
        """
        Split text into chunks of at most chunk_size characters.
        Tries to break on sentence boundaries ('. ', '! ', '? ', '\n').
        Falls back to hard character splits for very long runs.
        """
        if len(text) <= self.chunk_size:
            return [text]

        chunks: list[str] = []
        # Split on natural sentence boundaries
        sentences = re.split(r'(?<=[.!?\n])\s+', text)

        current = ""
        for sentence in sentences:
            # If a single sentence is longer than chunk_size, hard-split it
            if len(sentence) > self.chunk_size:
                if current:
                    chunks.append(current)
                    current = ""
                for i in range(0, len(sentence), self.chunk_size - self.overlap):
                    chunks.append(sentence[i : i + self.chunk_size])
                # Seed carry with overlap from last hard-split piece
                last = chunks[-1] if chunks else ""
                current = last[-self.overlap:] if len(last) > self.overlap else last
                continue

            if len(current) + len(sentence) + 1 <= self.chunk_size:
                current = (current + " " + sentence).strip() if current else sentence
            else:
                if current:
                    chunks.append(current)
                # Start new chunk with overlap from previous
                overlap_seed = current[-self.overlap:] if len(current) > self.overlap else current
                current = (overlap_seed + " " + sentence).strip()

        if current:
            chunks.append(current)

        return chunks if chunks else [text]

    @staticmethod
    def _make_chunk(text: str, source: str, chunk_id: int) -> dict:
        return {
            "text": text.strip(),
            "metadata": {
                "source": source,
                "chunk_id": chunk_id,
            },
        }
