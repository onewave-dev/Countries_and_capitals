from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set
import orjson


@dataclass
class DataSource:
    """In-memory representation of countries and capitals."""

    countries_by_continent: Dict[str, Set[str]]
    capital_by_country: Dict[str, str]
    country_by_capital: Dict[str, str]
    aliases: Dict[str, str]

    @classmethod
    def load(cls, path: str | Path) -> "DataSource":
        """Load data from a JSON file."""
        if isinstance(path, str):
            path = Path(path)
        with open(path, "rb") as f:
            raw = orjson.loads(f.read())

        countries_by_continent = {
            continent: set(countries)
            for continent, countries in raw.get("countries_by_continent", {}).items()
        }
        capital_by_country = raw.get("capital_by_country", {})
        country_by_capital = {cap: country for country, cap in capital_by_country.items()}
        aliases = {k.casefold(): v for k, v in raw.get("aliases", {}).items()}
        # allow case-insensitive matching for canonical names as well
        for name in list(capital_by_country.keys()) + list(capital_by_country.values()):
            aliases.setdefault(name.casefold(), name)

        return cls(
            countries_by_continent=countries_by_continent,
            capital_by_country=capital_by_country,
            country_by_capital=country_by_capital,
            aliases=aliases,
        )

    def normalize(self, name: str) -> str:
        """Normalize an input string using aliases."""
        return self.aliases.get(name.casefold(), name)

    def countries(self, continent: str | None = None) -> List[str]:
        if continent and continent in self.countries_by_continent:
            pool: Iterable[str] = self.countries_by_continent[continent]
        else:
            pool = {
                country for countries in self.countries_by_continent.values() for country in countries
            }
        return sorted(pool)

    def capitals(self, continent: str | None = None) -> List[str]:
        if continent and continent in self.countries_by_continent:
            countries = self.countries_by_continent[continent]
            pool = [self.capital_by_country[c] for c in countries]
        else:
            pool = self.capital_by_country.values()
        return sorted(pool)

    def items(self, continent: str | None, mode: str) -> List[str]:
        """Return a list of countries or capitals based on mode."""
        if mode == "country_to_capital":
            return self.countries(continent)
        if mode == "capital_to_country":
            return self.capitals(continent)
        # mixed
        return self.countries(continent) + self.capitals(continent)


@dataclass
class CardSession:
    user_id: int
    continent_filter: str | None = None
    mode: str = "mixed"
    queue: List[str] = field(default_factory=list)
    unknown_set: Set[str] = field(default_factory=set)
    stats: Dict[str, int] = field(default_factory=lambda: {"shown": 0, "known": 0})


@dataclass
class SprintSession:
    user_id: int
    duration_sec: int = 60
    start_ts: float | None = None
    score: int = 0
    questions_asked: int = 0


@dataclass
class CoopSession:
    session_id: str
    chat_id: int
    players: List[int] = field(default_factory=list)
    continent_filter: str | None = None
    mode: str = "mixed"
    difficulty: str = "easy"
    total_rounds: int = 10
    current_round: int = 0
    turn: int = 0
    team_score: int = 0
    bot_score: int = 0
    jobs: Dict[str, Any] = field(default_factory=dict)
