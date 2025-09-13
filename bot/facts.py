from __future__ import annotations

import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

_facts_path = Path(__file__).resolve().parents[1] / "data" / "facts_st.json"
# ``facts_st.json`` is bundled with the repository and contains static facts.
try:
    _facts: dict[str, list[str]] = json.loads(_facts_path.read_text(encoding="utf-8"))
except Exception:  # noqa: BLE001
    logger.warning("Failed to load %s", _facts_path)
    _facts = {}

def get_static_fact(country: str) -> str:
    """Return a random static fact about ``country``.

    If no fact is available, a fallback message is returned.
    """
    facts = _facts.get(country)
    if not facts:
        return "Интересный факт недоступен"
    return f"Интересный факт: {random.choice(facts)}"

__all__ = ["get_static_fact"]
