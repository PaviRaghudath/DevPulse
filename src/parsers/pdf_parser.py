"""PDF parser — page-by-page streaming via pypdf."""
import gc
from typing import Generator

from src.parsers.base_parser import BaseParser
from src.exceptions import ParseError


class PdfParser(BaseParser):
    """
    Reads a PDF one page at a time. Each page's extracted text is yielded
    as a separate segment. Pages are released from memory after extraction.
    Handles scanned/image PDFs gracefully (skips empty pages with a warning).
    """

    def supports(self, extension: str) -> bool:
        return extension.lower() == ".pdf"

    def parse(self, file_path: str) -> Generator[str, None, None]:
        try:
            import pypdf
        except ImportError:
            raise ParseError("pypdf is not installed. Run: pip install pypdf")

        try:
            reader = pypdf.PdfReader(file_path)
        except Exception as e:
            raise ParseError(f"Failed to open PDF '{file_path}': {e}") from e

        total_pages = len(reader.pages)
        empty_pages = 0

        for i in range(total_pages):
            try:
                page = reader.pages[i]
                text = page.extract_text() or ""
                # Release page object from memory
                del page
                if i % 50 == 0:
                    gc.collect()

                text = text.strip()
                if text:
                    yield text
                else:
                    empty_pages += 1
            except Exception as e:
                # Skip corrupted pages, continue processing the rest
                continue

        if empty_pages == total_pages:
            raise ParseError(
                f"No text could be extracted from '{file_path}'. "
                "The PDF may be scanned/image-only and requires OCR."
            )
