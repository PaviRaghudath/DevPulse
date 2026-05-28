"""Abstract base class for all file parsers."""
from abc import ABC, abstractmethod
from typing import Generator


class BaseParser(ABC):
    """
    All parsers implement parse() as a lazy generator of text segments.
    Each yielded string is a logical unit (page, paragraph batch, row batch).
    This ensures no parser loads the entire file into memory at once.
    """

    @abstractmethod
    def parse(self, file_path: str) -> Generator[str, None, None]:
        """Yield text segments from the file lazily."""
        ...

    @abstractmethod
    def supports(self, extension: str) -> bool:
        """Return True if this parser handles the given file extension (e.g. '.pdf')."""
        ...
