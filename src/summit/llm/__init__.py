"""LLM providers for SUMmit.

Kept deliberately empty. Importing :mod:`summit.llm.local` pulls in the Ollama
SDK and :mod:`summit.llm.cloud` pulls in the OpenAI SDK, so this package must
not re-export either one: doing so would load both clients on every
``import summit.llm`` and blow the cold-start budget.

Import the provider module you actually need:

    from summit.llm import local
    from summit.llm.prompts import build_prompt
"""

from __future__ import annotations

__all__: list[str] = []
