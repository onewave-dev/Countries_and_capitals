import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from bot.facts import get_static_fact


def test_known_country_fact():
    fact = get_static_fact("Россия")
    assert fact.startswith("Интересный факт: ")
    assert fact != "Интересный факт недоступен"


def test_unknown_country_fact():
    assert get_static_fact("Неизвестная страна") == "Интересный факт недоступен"
