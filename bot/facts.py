"""Fetch and cache random facts using OpenAI.

Facts are cached per subject and can be reused across modes.
"""

from __future__ import annotations

import os
import random

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

_cache: dict[str, list[str]] = {}


async def get_random_fact(subject: str) -> str:
    """Return a random fact about ``subject`` using OpenAI.

    Facts are cached per subject to avoid repeated API calls. Each fact is
    truncated to 150 characters. On any error a fallback string is returned.
    """

    facts = _cache.get(subject)
    if not facts:
        try:
            llm = ChatOpenAI(
                api_key=os.environ.get("OPENAI_API_KEY"), model="gpt-4o-mini"
            )
            prompt = (
                f"Назови 3 интересных факта о {subject}. Каждая строка ≤150 символов"
            )
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = getattr(response, "content", "")
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            facts = [line[:150] for line in lines][:3]
            if facts:
                _cache[subject] = facts
        except Exception:
            return "Интересный факт недоступен"

    if not facts:
        return "Интересный факт недоступен"
    return random.choice(facts)


__all__ = ["get_random_fact"]
