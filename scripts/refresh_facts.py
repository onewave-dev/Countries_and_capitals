#!/usr/bin/env python3
"""Refresh facts for countries and capitals using OpenAI only when outdated.

The script loads the list of subjects (countries and capitals) from
``data/capitals.json`` via :class:`bot.state.DataSource` and an existing cache
file ``data/facts.json`` if present. For each subject the cache entry is
inspected and refreshed via :func:`bot.facts.ensure_facts` only when its
``updated_at`` timestamp is older than :data:`bot.facts.FACTS_TTL` or the facts
list is missing. Fresh entries are reused. The resulting cache is written back
to ``data/facts.json``. A summary with the number of updated records is logged
on completion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from bot.facts import FACTS_TTL, ensure_facts
from bot.state import DataSource

ROOT = Path(__file__).resolve().parents[1]
CAPITALS_PATH = ROOT / "data" / "capitals.json"
FACTS_PATH = ROOT / "data" / "facts.json"


async def main() -> None:
    data = DataSource.load(CAPITALS_PATH)
    subjects = sorted(set(data.countries() + data.capitals()))

    existing: dict[str, dict[str, object]] = {}
    if FACTS_PATH.exists():
        raw = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
        for subject, value in raw.items():
            if isinstance(value, dict):
                existing[subject] = value
            else:
                existing[subject] = {"facts": value}

    results: dict[str, dict[str, object]] = {}
    updated = 0
    now = datetime.now(timezone.utc)

    for subject in subjects:
        entry = existing.get(subject, {})
        facts = entry.get("facts") if isinstance(entry, dict) else None
        updated_at_str = entry.get("updated_at") if isinstance(entry, dict) else None
        refresh = True

        if facts and isinstance(updated_at_str, str):
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
                refresh = now - updated_at > FACTS_TTL
            except ValueError:
                pass
            else:
                if not refresh:
                    results[subject] = {
                        "facts": list(facts),
                        "updated_at": updated_at_str,
                    }
                    continue

        new_facts = await ensure_facts(subject)
        if len(new_facts) < 3:
            raise RuntimeError(
                f"expected 3 facts for {subject}, got {len(new_facts)}"
            )
        results[subject] = {
            "facts": new_facts,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        updated += 1

    FACTS_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logging.info("Updated %d entries", updated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
