"""Fetch and cache random facts using OpenAI.

Facts are cached per subject and can be reused across modes. Cache can be
persisted on disk via ``FACTS_CACHE_PATH`` environment variable with a
time-to-live of 5 days.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

# subject -> {"facts": [..], "updated_at": datetime}
_cache: dict[str, dict[str, object]] = {}

FACTS_TTL = timedelta(days=5)
_cache_path_str = os.getenv("FACTS_CACHE_PATH")
_cache_path = Path(_cache_path_str).expanduser() if _cache_path_str else None


def _load_cache() -> None:
    if not _cache_path or not _cache_path.exists():
        return
    try:
        raw = json.loads(_cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    now = datetime.now(timezone.utc)
    for subject, entry in raw.items():
        facts = entry.get("facts")
        updated_at = entry.get("updated_at")
        if not facts or not updated_at:
            continue
        try:
            ts = datetime.fromisoformat(updated_at)
        except ValueError:
            continue
        if now - ts <= FACTS_TTL:
            _cache[subject] = {"facts": list(facts), "updated_at": ts}


def _save_cache() -> None:
    if not _cache_path:
        return
    data = {
        subject: {
            "facts": entry["facts"],
            "updated_at": entry["updated_at"].isoformat(),
        }
        for subject, entry in _cache.items()
    }
    tmp = _cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _cache_path)


def _expired(ts: datetime) -> bool:
    return datetime.now(timezone.utc) - ts > FACTS_TTL


async def _fetch_facts(subject: str) -> list[str]:
    llm = ChatOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"), model="gpt-4o-mini"
    )
    prompt = f"Назови 3 интересных факта о {subject}. Каждая строка ≤150 символов"
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    content = getattr(response, "content", "")
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return [line[:150] for line in lines][:3]


async def ensure_facts(subject: str) -> list[str]:
    entry = _cache.get(subject)
    if entry and not _expired(entry["updated_at"]):
        return entry["facts"]  # type: ignore[return-value]

    facts = await _fetch_facts(subject)
    if not facts:
        raise RuntimeError("no facts returned")
    entry = {"facts": facts, "updated_at": datetime.now(timezone.utc)}
    _cache[subject] = entry
    _save_cache()
    return facts


async def get_random_fact(subject: str) -> str:
    """Return a random fact about ``subject`` using OpenAI.

    Facts are cached per subject with optional persistence. Each fact is
    truncated to 150 characters. On any error a fallback string is returned.
    """

    try:
        facts = await ensure_facts(subject)
    except Exception:  # noqa: BLE001
        return "Интересный факт недоступен"
    return random.choice(facts) if facts else "Интересный факт недоступен"


async def preload_facts(subjects: Iterable[str]) -> None:
    """Preload facts for ``subjects`` with retries on failures."""

    for subject in subjects:
        for attempt in range(3):
            try:
                await ensure_facts(subject)
                break
            except Exception:  # noqa: BLE001
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)


_load_cache()


__all__ = ["get_random_fact", "ensure_facts", "preload_facts"]

