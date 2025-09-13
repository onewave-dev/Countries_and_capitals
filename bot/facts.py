"""Static facts loader."""

from __future__ import annotations

import json
import random
from pathlib import Path

# Load static facts at import time
_facts_path = Path(__file__).resolve().parents[1] / "data" / "facts_st.json"
try:
    _facts: dict[str, list[str]] = json.loads(_facts_path.read_text(encoding="utf-8"))
except Exception:  # noqa: BLE001
    _facts = {}


def get_static_fact(country: str) -> str:
    """Return a random fact for ``country`` prefixed with ``Интересный факт:``."""
    facts = _facts.get(country)
    if facts:
        return f"Интересный факт: {random.choice(facts)}"
    return "Интересный факт недоступен"
