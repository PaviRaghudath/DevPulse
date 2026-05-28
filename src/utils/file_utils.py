"""File validation and type detection utilities."""
import os
from pathlib import Path

from src.config import MAX_FILE_SIZE_MB, SUPPORTED_EXTENSIONS
from src.exceptions import (
    FileNotFoundError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)


def validate_file(file_path: str) -> Path:
    """
    Validate that the file exists, is a supported type, and is within size limits.
    Returns a resolved Path on success. Raises FileAnalyzerError subclasses on failure.
    """
    path = Path(file_path).resolve()

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not path.is_file():
        raise FileNotFoundError(f"Path is not a file: {file_path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    size_mb = path.stat().st_size / (1024 ** 2)
    if size_mb > MAX_FILE_SIZE_MB:
        raise FileTooLargeError(
            f"File is {size_mb:.1f}MB, which exceeds the {MAX_FILE_SIZE_MB}MB limit."
        )

    return path


def file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 ** 2)


def collection_name_from_path(file_path: str) -> str:
    """Derive a safe ChromaDB collection name from a file path."""
    import re
    stem = Path(file_path).stem
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", stem)
    # ChromaDB collection names: 3-63 chars, start/end with alphanumeric
    safe = safe.strip("_-")[:63]
    if len(safe) < 3:
        safe = (safe + "___")[:3]
    return safe
