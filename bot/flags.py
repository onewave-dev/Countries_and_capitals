"""Utility helpers for country flags."""
from __future__ import annotations

from functools import lru_cache

try:  # optional dependency
    import country_converter as coco  # type: ignore
except Exception:  # pragma: no cover - library may be missing
    coco = None  # type: ignore


def _code_to_flag(code: str) -> str:
    """Convert ISO alpha-2 country code to an emoji flag."""
    return ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in code.upper())


@lru_cache(maxsize=None)
def get_country_flag(country: str) -> str:
    """Return emoji flag for given country name.

    Uses :mod:`country_converter` if available to translate the country name
    (in various languages, including Russian) into an ISO alpha-2 code.
    If conversion fails or the library is missing, returns an empty string.
    """

    if not country:
        return ""

    if coco is not None:
        try:
            code = coco.convert(names=country, to="ISO2", not_found=None)
            if isinstance(code, str) and len(code) == 2:
                return _code_to_flag(code)
        except Exception:
            pass
    return ""
