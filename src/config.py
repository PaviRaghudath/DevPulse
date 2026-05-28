"""
Central configuration for FileAnalyzer.
All tuneable constants live here — no magic numbers elsewhere.
"""
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
VECTOR_STORE_PATH = str(BASE_DIR / "data" / "vector_store")

# ── File limits ────────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB = 500
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv", ".log"}

# ── Chunking ───────────────────────────────────────────────────────────────
CHUNK_SIZE = 512        # characters (~100-130 tokens; fits MiniLM 256-token limit)
CHUNK_OVERLAP = 64      # shared characters between adjacent chunks

# ── Embeddings ─────────────────────────────────────────────────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # 80MB download, 384-dim, CPU-fast
EMBEDDING_BATCH_SIZE = 64               # texts per encode() call

# ── Ingestion pipeline ─────────────────────────────────────────────────────
EMBED_BUFFER_SIZE = 200     # chunks accumulated before flush to ChromaDB
CSV_READ_CHUNK_ROWS = 10000 # pandas chunksize for CSV streaming
TXT_STREAM_BYTES = 65536    # 64KB read buffer for plain-text files

# ── Retrieval ──────────────────────────────────────────────────────────────
TOP_K_RETRIEVAL = 6         # chunks retrieved per query
MAX_CONTEXT_CHARS = 12000   # total characters sent to Claude as context

# ── LLM providers ──────────────────────────────────────────────────────────
LLM_MAX_TOKENS = 1024

# Anthropic (Claude)
CLAUDE_MODEL = "claude-sonnet-4-6"
ANTHROPIC_MODELS = [
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
]

# OpenAI (ChatGPT)
OPENAI_MODEL = "gpt-4o"
OPENAI_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
]

# Default provider ("anthropic" | "openai")
DEFAULT_PROVIDER = "openai"

# ── Document analysis ──────────────────────────────────────────────────────
ANALYSIS_SAMPLE_CHUNKS = 40     # chunks sampled for auto-analysis (no embedding needed)
ANALYSIS_MAX_TOKENS = 2048      # max tokens for the analysis LLM response

# ── Memory warnings ────────────────────────────────────────────────────────
MEMORY_WARN_MB = 1500       # warn if process RSS exceeds this

# ── Environment overrides ──────────────────────────────────────────────────
def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except ValueError:
        return default

def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)

CHUNK_SIZE = _env_int("CHUNK_SIZE", CHUNK_SIZE)
CHUNK_OVERLAP = _env_int("CHUNK_OVERLAP", CHUNK_OVERLAP)
EMBEDDING_MODEL = _env_str("EMBEDDING_MODEL", EMBEDDING_MODEL)
TOP_K_RETRIEVAL = _env_int("TOP_K_RETRIEVAL", TOP_K_RETRIEVAL)
