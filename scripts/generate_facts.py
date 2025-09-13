#!/usr/bin/env python3
"""Generate facts for every country using OpenAI.

The script reads ``data/capitals.json`` to obtain the list of countries and
queries OpenAI for three facts (each no longer than 150 characters) about each
country. Results are stored in ``data/facts.json``.

On any failure the script prints the error and exits with a non-zero status so
CI pipelines can detect the failure.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from bot.facts import ensure_facts

ROOT = Path(__file__).resolve().parents[1]
CAPITALS_PATH = ROOT / "data" / "capitals.json"
FACTS_PATH = ROOT / "data" / "facts.json"


async def main() -> None:
    data = json.loads(CAPITALS_PATH.read_text(encoding="utf-8"))
    countries = sorted(data["capital_by_country"].keys())

    results: dict[str, list[str]] = {}
    for country in countries:
        facts = await ensure_facts(country)
        if len(facts) < 3:
            raise RuntimeError(f"expected 3 facts for {country}, got {len(facts)}")
        results[country] = facts

    FACTS_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)