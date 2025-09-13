import sys
from pathlib import Path
import json

# add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.facts import get_static_fact


def test_get_static_fact():
    path = Path(__file__).resolve().parents[1] / "data" / "facts_st.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    facts = data["Канада"]
    fact = get_static_fact("Канада")
    prefix = "Интересный факт: "
    assert fact.startswith(prefix)
    assert fact[len(prefix):] in facts
