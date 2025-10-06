import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import app
from bot import subsets as subset_utils

if subset_utils.DATA is None:  # pragma: no cover - ensure dataset available during tests
    subset_utils.DATA = app.DATA


def test_select_matching_countries_identifies_duplicates():
    countries = ["Сингапур", "Люксембург", "Испания", "Германия"]
    result = subset_utils.select_matching_countries(countries)
    assert result == {"Сингапур", "Люксембург"}


def test_select_countries_by_letter_filters_case_insensitively():
    countries = ["Россия", "Испания", "Сингапур"]
    result_lower = subset_utils.select_countries_by_letter(countries, "м")
    result_upper = subset_utils.select_countries_by_letter(countries, "М")
    assert result_lower == {"Россия", "Испания"}
    assert result_upper == result_lower


def test_select_countries_by_letter_rejects_invalid_input():
    countries = ["Россия", "Испания"]
    assert subset_utils.select_countries_by_letter(countries, "1") == set()
    assert subset_utils.select_countries_by_letter(countries, "москва") == set()
    assert subset_utils.select_countries_by_letter(countries, "!") == set()


def test_select_remaining_countries_excludes_groups():
    base = {"Сингапур", "Люксембург", "Испания", "Россия", "Германия"}
    matching = subset_utils.select_matching_countries(base)
    letter_set = subset_utils.select_countries_by_letter(base, "м")
    others = subset_utils.select_remaining_countries(base, matching, letter_set)
    assert others == {"Германия"}
