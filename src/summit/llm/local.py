"""Local LLM inference via Ollama.

Wraps the Ollama Python SDK behind the provider interface SUMmit uses for every
backend: :func:`generate` turns a staged diff into a raw commit message, and
:func:`is_available` reports whether the server is reachable before the CLI
commits to a local run.

Every failure surfaces as a :class:`~summit.git_utils.SummitError` subclass with
a documented error code, so the caller never has to interpret an SDK exception.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
from ollama import Client, RequestError, ResponseError

from summit.git_utils import SummitError
from summit.llm.prompts import PromptContext, build_messages

logger = logging.getLogger(__name__)

#: Model used when the caller does not name one.
DEFAULT_MODEL = "codellama"

#: Default ceiling for a full generation, in seconds.
DEFAULT_TIMEOUT = 30

#: Short timeout for the availability probe, which must not stall startup.
PROBE_TIMEOUT = 2.0

#: Sampling options. Low temperature keeps commit messages deterministic and
#: factual; num_predict caps runaway generations that would blow the timeout.
GENERATION_OPTIONS: dict[str, float | int] = {
    "temperature": 0.2,
    "top_p": 0.9,
    "num_predict": 400,
}

_SETUP_HINT = (
    "Start it with `ollama serve`, or use a cloud model:\n"
    "  summit --model gpt-4o-mini"
)


class OllamaUnavailableError(SummitError):
    """Raised when the Ollama server cannot be reached."""

    code = "SUMMIT-003"
    exit_code = 3

    def __init__(self, detail: str | None = None) -> None:
        super().__init__("Ollama is not running.", hint=_SETUP_HINT)
        self.detail = detail


class GenerationTimeoutError(SummitError):
    """Raised when the model does not finish within the timeout."""

    code = "SUMMIT-004"
    exit_code = 4

    def __init__(self, timeout: float) -> None:
        super().__init__(
            f"Generation timed out after {timeout:g}s.",
            hint="Try a smaller diff, or a lighter model with `--model llama3.2`.",
        )
        self.timeout = timeout


class ModelNotFoundError(SummitError):
    """Raised when Ollama is running but does not have the requested model."""

    code = "SUMMIT-008"
    exit_code = 8

    def __init__(self, model: str) -> None:
        super().__init__(
            f"Model {model!r} is not installed.",
            hint=(
                f"Download it with `ollama pull {model}`, "
                "or list local models with `ollama list`."
            ),
        )
        self.model = model


class EmptyResponseError(SummitError):
    """Raised when the model returns no usable text."""

    code = "SUMMIT-005"
    exit_code = 5

    def __init__(self, model: str) -> None:
        super().__init__(
            f"Model {model!r} returned an empty response.",
            hint="Retry, or try a different model with `--model <name>`.",
        )
        self.model = model


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """A completed generation and the metrics the UI displays.

    Attributes:
        text: Raw model output, before parsing.
        model: Model that produced it, as reported by the server.
        elapsed: Wall-clock seconds spent in the call.
    """

    text: str
    model: str
    elapsed: float


def _build_client(timeout: float) -> Client:
    """Construct an Ollama client with an explicit request timeout.

    Args:
        timeout: Per-request timeout in seconds, forwarded to the underlying
            HTTP client.

    Returns:
        A configured :class:`~ollama.Client`. The host comes from the
        ``OLLAMA_HOST`` environment variable when set, otherwise the SDK
        default of ``http://127.0.0.1:11434``.
    """
    return Client(timeout=timeout)


def is_available(timeout: float = PROBE_TIMEOUT) -> bool:
    """Check whether the Ollama server answers.

    Never raises: this is a branch point for the CLI's local-vs-cloud decision,
    not an error condition.

    Args:
        timeout: Seconds to wait for the probe. Kept short so a dead server does
            not stall startup.

    Returns:
        ``True`` if the server responded to a model listing, ``False`` otherwise.
    """
    try:
        _build_client(timeout).list()
    except (ConnectionError, httpx.HTTPError, RequestError, ResponseError, OSError) as exc:
        logger.debug("Ollama availability probe failed: %s", type(exc).__name__)
        return False
    return True


def list_models(timeout: float = PROBE_TIMEOUT) -> list[str]:
    """List the models installed on the Ollama server.

    Args:
        timeout: Seconds to wait for the request.

    Returns:
        Model names, e.g. ``["codellama:latest", "llama3.2:3b"]``. Empty if the
        server is unreachable or has no models.
    """
    try:
        response = _build_client(timeout).list()
    except (ConnectionError, httpx.HTTPError, RequestError, ResponseError, OSError) as exc:
        logger.debug("Could not list Ollama models: %s", type(exc).__name__)
        return []

    return [entry.model for entry in response.models if entry.model]


def _is_model_missing(exc: ResponseError) -> bool:
    """Decide whether a server error means the model is not installed.

    Args:
        exc: Error raised by the Ollama SDK.

    Returns:
        ``True`` for a 404, or for a message that names a missing model.
    """
    if exc.status_code == 404:
        return True
    text = (exc.error or "").lower()
    return "not found" in text or "try pulling it first" in text


def generate_with_metrics(
    diff: str,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
    context: PromptContext | None = None,
) -> GenerationResult:
    """Generate a commit message and report timing alongside it.

    Args:
        diff: Staged diff, already secret-redacted by
            :func:`summit.git_utils.get_staged_diff`.
        model: Ollama model tag, e.g. ``"codellama"`` or ``"llama3.2:3b"``.
        timeout: Seconds to allow for the request.
        context: Repository context injected into the prompt, if available.

    Returns:
        The raw output with the model name and elapsed time.

    Raises:
        ValueError: If ``diff`` is empty, or ``model`` is blank.
        OllamaUnavailableError: If the server is not reachable.
        GenerationTimeoutError: If the request exceeds ``timeout``.
        ModelNotFoundError: If the server does not have ``model``.
        EmptyResponseError: If the model returns no text.
    """
    if not model.strip():
        raise ValueError("Model name cannot be empty.")

    # Raises ValueError on an empty diff, before any network work.
    messages = build_messages(diff, context)

    logger.info("Generating commit message with local model %r.", model)
    started = time.monotonic()

    try:
        response = _build_client(timeout).chat(
            model=model,
            messages=messages,
            stream=False,
            options=GENERATION_OPTIONS,
        )
    except httpx.TimeoutException as exc:
        raise GenerationTimeoutError(timeout) from exc
    except ResponseError as exc:
        if _is_model_missing(exc):
            raise ModelNotFoundError(model) from exc
        # A non-404 server error still means local generation is unusable.
        logger.error("Ollama returned an error: %s", exc.error)
        raise OllamaUnavailableError(exc.error) from exc
    except (ConnectionError, httpx.HTTPError, RequestError, OSError) as exc:
        raise OllamaUnavailableError(str(exc)) from exc

    elapsed = time.monotonic() - started

    # stream=False guarantees a single ChatResponse rather than an iterator.
    text = (response.message.content or "").strip()
    if not text:
        raise EmptyResponseError(model)

    logger.info("Generated %d chars in %.2fs via %r.", len(text), elapsed, model)
    return GenerationResult(text=text, model=response.model or model, elapsed=elapsed)


def generate(
    diff: str,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
    context: PromptContext | None = None,
) -> str:
    """Generate a commit message from a staged diff.

    Thin wrapper over :func:`generate_with_metrics` for callers that only need
    the text.

    Args:
        diff: Staged diff, already secret-redacted.
        model: Ollama model tag.
        timeout: Seconds to allow for the request.
        context: Repository context injected into the prompt, if available.

    Returns:
        The raw model output, stripped of surrounding whitespace. Parsing into a
        structured message is :mod:`summit.parser`'s job.

    Raises:
        ValueError: If ``diff`` is empty, or ``model`` is blank.
        OllamaUnavailableError: If the server is not reachable.
        GenerationTimeoutError: If the request exceeds ``timeout``.
        ModelNotFoundError: If the server does not have ``model``.
        EmptyResponseError: If the model returns no text.
    """
    return generate_with_metrics(diff, model, timeout, context).text
