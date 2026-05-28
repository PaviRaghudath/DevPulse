"""CSV parser — chunked pandas streaming with schema preamble."""
import gc
from typing import Generator

from src.config import CSV_READ_CHUNK_ROWS
from src.parsers.base_parser import BaseParser
from src.exceptions import ParseError


class CsvParser(BaseParser):
    """
    First yields a schema description (column names + sample row).
    Then streams rows in CSV_READ_CHUNK_ROWS chunks, converting each to
    a text block suitable for embedding. Memory usage is bounded by chunksize.
    """

    def supports(self, extension: str) -> bool:
        return extension.lower() == ".csv"

    def parse(self, file_path: str) -> Generator[str, None, None]:
        try:
            import pandas as pd
        except ImportError:
            raise ParseError("pandas is not installed. Run: pip install pandas")

        try:
            # Read a small sample first for schema context
            sample = pd.read_csv(file_path, nrows=3, low_memory=False)
        except Exception as e:
            raise ParseError(f"Failed to read CSV '{file_path}': {e}") from e

        columns = list(sample.columns)
        yield f"CSV dataset with {len(columns)} columns: {', '.join(columns)}"

        # Show one sample row as context
        if not sample.empty:
            sample_row = sample.iloc[0].to_dict()
            sample_str = ", ".join(f"{k}: {v}" for k, v in sample_row.items())
            yield f"Sample row — {sample_str}"

        # Stream all rows in chunks
        try:
            for chunk_df in pd.read_csv(
                file_path,
                chunksize=CSV_READ_CHUNK_ROWS,
                low_memory=False,
                on_bad_lines="skip",
            ):
                # Convert chunk to a readable string block
                text = chunk_df.to_string(index=False, max_cols=30)
                yield text
                del chunk_df
                gc.collect()
        except Exception as e:
            raise ParseError(f"Error streaming CSV '{file_path}': {e}") from e
