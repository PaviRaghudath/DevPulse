# FileAnalyzer — Developer Rules

## Documentation Rule (MANDATORY)
Any change that modifies project structure, design, CLI commands, configuration constants,
or dependencies **must** include a corresponding update to `README.md` in the same session.

This means:
- Adding/removing/renaming files → update the Project Structure section in README.md
- Adding/changing a CLI command → update the CLI Reference section
- Changing a config constant → update the Configuration table
- Adding/removing/upgrading a dependency → update the Dependencies section
- Changing the architecture or data flow → update the Architecture section

README.md is the single source of truth for this project. Keep it accurate.

## Project Overview
RAG-based document Q&A agent with Streamlit web UI.
Primary entry point: `app.py` (run with `streamlit run app.py`)
Pipeline: File → Parser → Chunker → EmbeddingEngine → VectorStore → Retriever → LLMClient (OpenAI or Anthropic)

## Key Design Constraints
- All parsers must use streaming generators — never load entire file into memory
- Chunk buffer in pipeline must not exceed EMBED_BUFFER_SIZE (200) before flushing
- ChromaDB is the only vector store — do not switch to FAISS without updating Windows install docs
- LLMClient supports both "openai" and "anthropic" providers — update both if changing the interface
- Model lists live in `src/config.py` (OPENAI_MODELS, ANTHROPIC_MODELS) — update + README when adding models
- UI lives entirely in `app.py` — backend modules (src/) have no Streamlit imports

## Adding a New AI Provider
1. Add a `_ask_<provider>()` method to `LLMClient` in `src/llm.py`
2. Add the provider name to the `Provider` type alias and `ask_stream()` dispatch
3. Add model list constant to `src/config.py`
4. Add the radio option in `render_sidebar()` in `app.py`
5. Update README.md — AI Providers section

## Adding a New File Type
1. Create `src/parsers/<type>_parser.py` implementing `BaseParser`
2. Register it in `IngestionPipeline._parsers` in `src/pipeline.py`
3. Add the extension to `SUPPORTED_EXTENSIONS` in `src/config.py`
4. Update README.md — File Type Support section
