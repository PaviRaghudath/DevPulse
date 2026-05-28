"""Rich-based progress bars and spinners for FileAnalyzer."""
from contextlib import contextmanager
from typing import Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


console = Console()


@contextmanager
def ingestion_progress(description: str, total: Optional[int] = None):
    """
    Context manager yielding a Rich Progress task for ingestion steps.
    If total is None the bar shows a pulse (indeterminate).

    Usage:
        with ingestion_progress("Embedding chunks", total=1800) as (progress, task):
            for batch in batches:
                process(batch)
                progress.advance(task, len(batch))
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(description, total=total)
        yield progress, task


@contextmanager
def spinner(message: str):
    """
    Simple spinner context manager for short indeterminate operations
    (e.g., Claude API call, model loading).

    Usage:
        with spinner("Thinking..."):
            result = call_api()
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(message, total=None)
        yield
