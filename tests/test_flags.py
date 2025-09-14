import json
import sys
from pathlib import Path

# add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.flags import get_country_flag  # noqa: E402


def test_all_countries_have_flag():
    data = json.loads(Path('data/capitals.json').read_text(encoding='utf-8'))
    missing = [c for c in data['capital_by_country'] if not get_country_flag(c)]
    assert not missing, f"Missing flags for: {missing}"
