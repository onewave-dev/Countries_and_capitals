"""Static facts loader."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
import logging

from openai import AsyncOpenAI

# Load static facts at import time
_facts_path = Path(__file__).resolve().parents[1] / "data" / "facts_st.json"
try:
    _facts: dict[str, list[str]] = json.loads(_facts_path.read_text(encoding="utf-8"))
except Exception:  # noqa: BLE001
    _facts = {}

logger = logging.getLogger(__name__)
try:  # Gracefully handle missing API key during tests
    _client: AsyncOpenAI | None = AsyncOpenAI()
except Exception:  # noqa: BLE001
    _client = None

_llm_model = os.getenv("OPENAI_LLM_MODEL", "gpt-3.5-turbo")


def get_static_fact(country: str) -> str:
    """Return a random fact for ``country`` prefixed with ``Интересный факт:``."""
    facts = _facts.get(country)
    if facts:
        return f"Интересный факт: {random.choice(facts)}"
    return "Интересный факт недоступен"


async def generate_llm_fact(country: str, exclude: str) -> str:
    """Generate an additional fact about ``country`` avoiding ``exclude``.

    The returned string is trimmed to 150 characters. Any errors during the
    API call result in a fallback message.
    """

    prompt = (
        f"Сообщи один интересный факт о стране {country}. "
        f"Не повторяй этот факт: {exclude}. "
        "Ответ не длиннее 150 символов."
    )
    if not _client:
        return "Факт недоступен"
    try:
        kwargs = {
            "model": _llm_model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if _llm_model.startswith("o"):
            kwargs["max_completion_tokens"] = 80
        else:
            kwargs["max_tokens"] = 80
        resp = await _client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content.strip().replace("\n", " ")
        return text[:150]
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM fact generation failed: %s", e)
        return "Факт недоступен"
