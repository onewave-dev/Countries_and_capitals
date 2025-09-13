#!/usr/bin/env python3
"""Generate facts for countries and capitals using OpenAI.

The script reads ``data/capitals.json`` via :class:`bot.state.DataSource` to
obtain the list of countries **and** capitals. For each subject OpenAI is
queried for three facts (each no longer than 150 characters). Results are
stored in ``data/facts.json`` using the subject as the key and including the
``updated_at`` timestamp.

On any failure the script prints the error and exits with a non-zero status so
CI pipelines can detect the failure.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from bot.facts import ensure_facts
from bot.state import DataSource

ROOT = Path(__file__).resolve().parents[1]
CAPITALS_PATH = ROOT / "data" / "capitals.json"
FACTS_PATH = ROOT / "data" / "facts.json"


async def main() -> None:
    data = DataSource.load(CAPITALS_PATH)
    subjects = sorted(set(data.countries() + data.capitals()))

    results: dict[str, dict[str, object]] = {}
    for subject in subjects:
        facts = await ensure_facts(subject)
        if len(facts) < 3:
            raise RuntimeError(f"expected 3 facts for {subject}, got {len(facts)}")
        results[subject] = {
            "facts": facts,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    FACTS_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
