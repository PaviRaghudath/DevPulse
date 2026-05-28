"""
LLMClient — unified streaming client supporting OpenAI and Anthropic (Claude).

Usage:
    client = LLMClient(provider="openai", api_key="sk-...", model="gpt-4o")
    for token in client.ask_stream(question, context):
        print(token, end="", flush=True)
"""
import time
from typing import Generator, Literal

from src.config import LLM_MAX_TOKENS
from src.exceptions import APIError

Provider = Literal["openai", "anthropic"]

_SYSTEM_PROMPT = """You are a precise document analysis assistant.
Answer questions strictly based on the provided document context.
If the context does not contain enough information to answer, say so clearly.
Do not hallucinate or add information not present in the context.
When possible, reference which excerpt supports your answer."""

_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 3, 7]


class LLMClient:
    def __init__(self, provider: Provider, api_key: str, model: str):
        if provider not in ("openai", "anthropic"):
            raise APIError(f"Unknown provider '{provider}'. Choose 'openai' or 'anthropic'.")
        self.provider = provider
        self.api_key = api_key
        self.model = model

    # ── Public API ────────────────────────────────────────────────────────

    def ask_stream(self, question: str, context: str) -> Generator[str, None, None]:
        """
        Stream an answer to `question` grounded in `context`.
        Yields string tokens as they arrive from the API.
        Retries up to _MAX_RETRIES times on transient errors.
        """
        if self.provider == "openai":
            yield from self._with_retry(self._ask_openai, question, context)
        else:
            yield from self._with_retry(self._ask_anthropic, question, context)

    # ── OpenAI ────────────────────────────────────────────────────────────

    def _ask_openai(self, question: str, context: str) -> Generator[str, None, None]:
        try:
            from openai import OpenAI
        except ImportError:
            raise APIError(
                "openai package is not installed. Run: pip install openai"
            )

        user_msg = (
            f"Document context:\n\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Answer based only on the document context above:"
        )

        try:
            client = OpenAI(api_key=self.api_key)
            stream = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                stream=True,
                max_tokens=LLM_MAX_TOKENS,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            err = str(e)
            if "401" in err or "api_key" in err.lower() or "authentication" in err.lower():
                raise APIError(
                    "OpenAI authentication failed. Check your API key."
                ) from e
            raise APIError(f"OpenAI API error: {e}") from e

    # ── Anthropic ─────────────────────────────────────────────────────────

    def _ask_anthropic(self, question: str, context: str) -> Generator[str, None, None]:
        try:
            import anthropic
        except ImportError:
            raise APIError(
                "anthropic package is not installed. Run: pip install anthropic"
            )

        user_msg = (
            f"Document context:\n\n{context}\n\n"
            f"Question: {question}\n\n"
            f"Answer based only on the document context above:"
        )

        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            with client.messages.stream(
                model=self.model,
                max_tokens=LLM_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as e:
            err = str(e)
            if "401" in err or "api_key" in err.lower() or "authentication" in err.lower():
                raise APIError(
                    "Anthropic authentication failed. Check your API key."
                ) from e
            raise APIError(f"Anthropic API error: {e}") from e

    def complete(self, prompt: str) -> str:
        """
        Non-streaming direct completion for internal use (e.g. document analysis).
        Sends `prompt` as the sole user message with no RAG context framing.
        Returns the full response text.
        """
        if self.provider == "openai":
            return self._complete_openai(prompt)
        return self._complete_anthropic(prompt)

    def _complete_openai(self, prompt: str) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            raise APIError("openai package is not installed. Run: pip install openai")
        try:
            client = OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise APIError(f"OpenAI complete error: {e}") from e

    def _complete_anthropic(self, prompt: str) -> str:
        try:
            import anthropic
        except ImportError:
            raise APIError("anthropic package is not installed. Run: pip install anthropic")
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            message = client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text if message.content else ""
        except Exception as e:
            raise APIError(f"Anthropic complete error: {e}") from e

    # ── Retry wrapper ─────────────────────────────────────────────────────

    def _with_retry(self, fn, question: str, context: str) -> Generator[str, None, None]:
        last_error = None
        for attempt in range(_MAX_RETRIES):
            try:
                yield from fn(question, context)
                return
            except APIError:
                raise  # auth errors and explicit API errors: don't retry
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAYS[attempt])
        raise APIError(
            f"API call failed after {_MAX_RETRIES} attempts: {last_error}"
        ) from last_error
