"""Plain-text parser — 64KB block streaming with paragraph-boundary yields."""
from typing import Generator

from src.config import TXT_STREAM_BYTES
from src.parsers.base_parser import BaseParser
from src.exceptions import ParseError


class TxtParser(BaseParser):
    """
    Reads the file in TXT_STREAM_BYTES (64KB) blocks, accumulates into a buffer,
    and yields on double-newline paragraph boundaries. The file is never fully
    loaded into memory — only the current block + carry buffer is held at once.
    """

    def supports(self, extension: str) -> bool:
        return extension.lower() in (".txt", ".log")

    def parse(self, file_path: str) -> Generator[str, None, None]:
        try:
            buffer = ""
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                while True:
                    block = f.read(TXT_STREAM_BYTES)
                    if not block:
                        break
                    buffer += block
                    # Split on paragraph boundaries (double newline)
                    parts = buffer.split("\n\n")
                    for part in parts[:-1]:
                        part = part.strip()
                        if part:
                            yield part
                    # Keep the last (possibly incomplete) part as carry
                    buffer = parts[-1]

            # Yield whatever remains
            if buffer.strip():
                yield buffer.strip()

        except OSError as e:
            raise ParseError(f"Failed to read text file '{file_path}': {e}") from e
