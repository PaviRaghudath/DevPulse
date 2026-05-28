"""Custom exception hierarchy for FileAnalyzer."""


class FileAnalyzerError(Exception):
    """Base exception for all FileAnalyzer errors."""


class UnsupportedFileTypeError(FileAnalyzerError):
    """Raised when a file extension is not supported."""


class FileTooLargeError(FileAnalyzerError):
    """Raised when a file exceeds MAX_FILE_SIZE_MB."""


class FileNotFoundError(FileAnalyzerError):
    """Raised when the specified file does not exist."""


class ParseError(FileAnalyzerError):
    """Raised when a parser fails to read a file."""


class EmbeddingError(FileAnalyzerError):
    """Raised when the embedding engine fails."""


class APIError(FileAnalyzerError):
    """Raised when the Claude API call fails."""


class CollectionNotFoundError(FileAnalyzerError):
    """Raised when a requested ChromaDB collection does not exist."""
