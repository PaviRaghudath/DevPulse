"""
FileAnalyzer CLI — entry point.

Commands:
  load  <file>           Index a document into the vector store
  ask   <file> <q>       Answer a single question about a document
  chat  <file>           Interactive Q&A session with a document
  list                   List all indexed documents
  clear <file>           Remove a document's index
"""
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

load_dotenv()

console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        console.print(
            "[red]Error:[/red] ANTHROPIC_API_KEY is not set. "
            "Add it to your .env file or environment."
        )
        sys.exit(1)
    return key


def _build_components(file_path: str, force: bool = False):
    """Instantiate and return pipeline, retriever, llm for a given file."""
    from src.embeddings import EmbeddingEngine
    from src.vector_store import VectorStore
    from src.pipeline import IngestionPipeline
    from src.retriever import Retriever
    from src.llm import ClaudeClient
    from src.utils.file_utils import collection_name_from_path
    from src.utils.progress import ingestion_progress

    engine = EmbeddingEngine()
    store = VectorStore()
    pipeline = IngestionPipeline(engine, store)

    # Check if already indexed
    collection_name = collection_name_from_path(file_path)
    already_indexed = store.collection_exists(collection_name)

    if already_indexed and not force:
        console.print(
            f"[green]Document already indexed[/green] ({collection_name}). "
            "Use --force to re-index."
        )
        store.get_or_create_collection(collection_name)
    else:
        verb = "Re-indexing" if (already_indexed and force) else "Indexing"
        console.print(f"[bold]{verb}[/bold] [cyan]{Path(file_path).name}[/cyan]...")

        total_chunks = [0]

        with ingestion_progress("Processing document") as (progress, task):
            def on_progress(n: int):
                total_chunks[0] += n
                progress.advance(task, n)

            try:
                result = pipeline.ingest(file_path, force_reindex=force, on_progress=on_progress)
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
                sys.exit(1)

        console.print(
            f"[green]Done.[/green] {result.chunk_count} chunks indexed "
            f"in {result.duration_seconds:.1f}s"
        )

    api_key = _get_api_key()
    retriever = Retriever(engine, store)
    llm = ClaudeClient(api_key)
    return retriever, llm


# ── Commands ──────────────────────────────────────────────────────────────

@click.group()
def cli():
    """FileAnalyzer — ask questions about PDF, DOCX, TXT, and CSV files."""


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Re-index even if already indexed.")
def load(file_path: str, force: bool):
    """Index a document so it can be queried."""
    from src.embeddings import EmbeddingEngine
    from src.vector_store import VectorStore
    from src.pipeline import IngestionPipeline
    from src.utils.progress import ingestion_progress

    engine = EmbeddingEngine()
    store = VectorStore()
    pipeline = IngestionPipeline(engine, store)

    from src.utils.file_utils import collection_name_from_path
    collection_name = collection_name_from_path(file_path)

    if store.collection_exists(collection_name) and not force:
        console.print(
            f"[yellow]Already indexed.[/yellow] Use --force to re-index."
        )
        return

    console.print(f"Indexing [cyan]{Path(file_path).name}[/cyan]...")

    with ingestion_progress("Processing document") as (progress, task):
        def on_progress(n: int):
            progress.advance(task, n)

        try:
            result = pipeline.ingest(file_path, force_reindex=force, on_progress=on_progress)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

    console.print(
        f"[green]Indexed[/green] {result.chunk_count} chunks "
        f"in {result.duration_seconds:.1f}s — collection: [dim]{collection_name}[/dim]"
    )


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.argument("question")
@click.option("--force", is_flag=True, help="Re-index even if already indexed.")
def ask(file_path: str, question: str, force: bool):
    """Answer a single question about a document."""
    retriever, llm = _build_components(file_path, force)

    chunks = retriever.retrieve(question)
    if not chunks:
        console.print("[yellow]No relevant content found for that question.[/yellow]")
        return

    context = retriever.build_context(chunks)

    console.print()
    console.print(Panel(Text(question, style="bold"), title="Question", border_style="blue"))
    console.print()
    console.print("[bold green]Answer:[/bold green]")

    for token in llm.ask_stream(question, context):
        console.print(token, end="")
    console.print()


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Re-index even if already indexed.")
def chat(file_path: str, force: bool):
    """Start an interactive Q&A session with a document."""
    retriever, llm = _build_components(file_path, force)

    console.print()
    console.print(
        Panel(
            f"[bold]Document:[/bold] {Path(file_path).name}\n"
            "[dim]Type your questions and press Enter. Type 'quit' or 'exit' to stop.[/dim]",
            title="FileAnalyzer Chat",
            border_style="green",
        )
    )
    console.print()

    while True:
        try:
            question = console.input("[bold blue]You:[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not question:
            continue
        if question.lower() in {"quit", "exit", "q"}:
            console.print("[dim]Goodbye.[/dim]")
            break

        chunks = retriever.retrieve(question)
        if not chunks:
            console.print("[yellow]No relevant content found for that question.[/yellow]\n")
            continue

        context = retriever.build_context(chunks)

        console.print()
        console.print("[bold green]Assistant:[/bold green] ", end="")
        try:
            for token in llm.ask_stream(question, context):
                console.print(token, end="")
        except Exception as e:
            console.print(f"\n[red]Error:[/red] {e}")
        console.print("\n")


@cli.command(name="list")
def list_docs():
    """List all indexed documents."""
    from src.vector_store import VectorStore
    store = VectorStore()
    collections = store.list_collections()

    if not collections:
        console.print("[yellow]No documents indexed yet.[/yellow]")
        console.print("Use [bold]load <file>[/bold] to index a document.")
        return

    console.print(f"\n[bold]Indexed documents[/bold] ({len(collections)}):\n")
    for name in collections:
        count = store.collection_count(name)
        console.print(f"  [cyan]{name}[/cyan]  [dim]({count} chunks)[/dim]")
    console.print()


@cli.command()
@click.argument("file_path")
def clear(file_path: str):
    """Remove a document's index from the vector store."""
    from src.vector_store import VectorStore
    from src.utils.file_utils import collection_name_from_path
    from src.exceptions import CollectionNotFoundError

    store = VectorStore()
    collection_name = collection_name_from_path(file_path)

    try:
        store.delete_collection(collection_name)
        console.print(f"[green]Removed index[/green] for [cyan]{collection_name}[/cyan].")
    except CollectionNotFoundError:
        console.print(
            f"[yellow]No index found[/yellow] for '{collection_name}'. "
            "Use [bold]list[/bold] to see indexed documents."
        )


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
