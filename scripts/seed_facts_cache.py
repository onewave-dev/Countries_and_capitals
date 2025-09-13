#!/usr/bin/env python3
"""Seed facts cache file for deployments.

This script prepares a JSON file in the format expected by ``bot.facts``.
It can either create an empty cache or convert ``data/facts.json``
(which maps subject to list of facts) into the cache structure with
``updated_at`` timestamps.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FACTS = ROOT / "data" / "facts.json"

def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare facts cache file")
    parser.add_argument("path", nargs="?", default=os.getenv("FACTS_CACHE_PATH"))
    parser.add_argument(
        "--from-data",
        action="store_true",
        help="convert data/facts.json into cache format",
    )
    args = parser.parse_args()

    if not args.path:
        raise SystemExit("cache path must be provided or FACTS_CACHE_PATH set")

    path = Path(args.path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if args.from_data and DATA_FACTS.exists():
        raw = json.loads(DATA_FACTS.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc).isoformat()
        data = {k: {"facts": v, "updated_at": now} for k, v in raw.items()}
    else:
        data = {}

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
