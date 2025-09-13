"""Fetch and cache random facts using OpenAI.

Facts are cached per subject and can be reused across modes. Cache can be
persisted on disk via ``FACTS_CACHE_PATH`` environment variable with a
time-to-live of 5 days.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

# subject -> {"facts": [..], "updated_at": datetime}
_cache: dict[str, dict[str, object]] = {}

# fallback facts shipped with the repository
_reserve_facts_path = (
    Path(__file__).resolve().parents[1] / "data" / "facts_reserve.json"
)
try:
    _reserve_facts: dict[str, list[str]] = json.loads(
        _reserve_facts_path.read_text(encoding="utf-8")
    )
except Exception:  # noqa: BLE001
    _reserve_facts = {}

FACTS_TTL = timedelta(days=5)

logger = logging.getLogger(__name__)

_cache_path_str = os.getenv("FACTS_CACHE_PATH")
_cache_path = Path(_cache_path_str).expanduser() if _cache_path_str else None
_logger = logging.getLogger(__name__)


def _load_cache() -> None:
    global _cache_path

    if not _cache_path:
        logger.warning(
            "FACTS_CACHE_PATH env var is not set; facts cache will not persist"
        )
        return

    try:
        _cache_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning(
            "FACTS_CACHE_PATH '%s' is not writable; facts cache will not persist",
            _cache_path,
        )
        _cache_path = None
        return

    writable = (
        os.access(_cache_path, os.W_OK)
        if _cache_path.exists()
        else os.access(_cache_path.parent, os.W_OK)
    )
    if not writable:
        logger.warning(
            "FACTS_CACHE_PATH '%s' is not writable; facts cache will not persist",
            _cache_path,
        )
        _cache_path = None
        return

    if not _cache_path.exists():
        return

    try:
        raw = json.loads(_cache_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    now = datetime.now(timezone.utc)
    for subject, entry in raw.items():
        if not isinstance(entry, dict):
            continue
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



def random_reserve_fact(subject: str) -> str | None:
    """Return a random bundled fact about ``subject``.

    The result is suffixed with ``" *"`` to mark it as a fallback.
    """

    facts = _reserve_facts.get(subject)
    if not facts:
        return None
    return random.choice(facts) + " *"



async def get_random_fact(subject: str, *, reserve_subject: str | None = None) -> str:
    """Return a random fact about ``subject``.

    Facts are fetched from OpenAI and cached. If fetching fails, a reserve fact
    bundled with the repository is returned for ``reserve_subject`` (or
    ``subject`` if it is ``None``). Each fact is prefixed with
    ``"Интересный факт: "``. If no fact can be provided, a fallback message is
    returned.
    """

    try:
        facts = await ensure_facts(subject)
    except Exception:  # noqa: BLE001
        facts = []

    if facts:
        return f"Интересный факт: {random.choice(facts)}"

    async def _wrap() -> None:
        try:
            await ensure_facts(subject)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to refresh facts for %s", subject)

    asyncio.create_task(_wrap())
    reserve = random_reserve_fact(reserve_subject or subject)
    if reserve:
        return f"Интересный факт: {reserve}"
    return "Интересный факт недоступен"

async def preload_facts(subjects: Iterable[str]) -> None:
    """Preload facts for ``subjects`` with exponential backoff."""

    for subject in subjects:
        attempt = 0
        while attempt < 3:
            try:
                await ensure_facts(subject)
                break
            except Exception as err:  # noqa: BLE001
                status = getattr(err, "status_code", None) or getattr(
                    err, "http_status", None
                )
                headers = getattr(getattr(err, "response", None), "headers", {})
                if status == 429:
                    retry_after = headers.get("Retry-After") or headers.get(
                        "retry-after"
                    )
                    try:
                        delay = float(retry_after)
                    except (TypeError, ValueError):
                        delay = 1.0
                    delay *= 2**attempt
                    remaining = headers.get("x-ratelimit-remaining-requests") or headers.get(
                        "x-ratelimit-remaining-tokens"
                    )
                    _logger.warning(
                        "Rate limit hit for %s (attempt %s), retrying in %.1fs (remaining %s)",
                        subject,
                        attempt + 1,
                        delay,
                        remaining,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                _logger.warning("Error preloading facts for %s: %s", subject, err)
                if attempt < 2:
                    delay = 2**attempt
                    _logger.warning("Retrying %s in %.1fs", subject, delay)
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                break


_load_cache()

__all__ = [
    "get_random_fact",
    "ensure_facts",
    "preload_facts",
    "random_reserve_fact",
]
