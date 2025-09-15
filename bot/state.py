from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

import orjson
from telegram.ext import Job


@dataclass
class DataSource:
    """In-memory representation of countries and capitals."""

    countries_by_continent: Dict[str, Set[str]]
    capital_by_country: Dict[str, str]
    country_by_capital: Dict[str, str]
    country_to_continent: Dict[str, str]
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
        country_to_continent = {
            country: continent
            for continent, countries in countries_by_continent.items()
            for country in countries
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
            country_to_continent=country_to_continent,
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

    def continent_of_country(self, country: str) -> str | None:
        return self.country_to_continent.get(country)

    def continent_of_capital(self, capital: str) -> str | None:
        country = self.country_by_capital.get(capital)
        if country:
            return self.country_to_continent.get(country)
        return None

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
    fact_message_id: int | None = None
    fact_subject: str | None = None
    fact_text: str | None = None
    current_answered: bool = False


@dataclass
class TestSession:
    user_id: int
    queue: List[str] = field(default_factory=list)
    unknown_set: Set[str] = field(default_factory=set)
    stats: Dict[str, int] = field(default_factory=lambda: {"total": 0, "correct": 0})
    total_questions: int = 0
    fact_message_id: int | None = None
    fact_subject: str | None = None
    fact_text: str | None = None


@dataclass
class SprintSession:
    user_id: int
    duration_sec: int = 60
    start_ts: float | None = None
    score: int = 0
    questions_asked: int = 0
    wrong_answers: list[tuple[str, str]] = field(default_factory=list)
    asked_countries: set[str] = field(default_factory=set)


@dataclass
class CoopSession:
    session_id: str
    players: List[int] = field(default_factory=list)
    player_chats: Dict[int, int] = field(default_factory=dict)
    player_names: Dict[int, str] = field(default_factory=dict)
    continent_filter: str | None = None
    mode: str = "mixed"
    difficulty: str = ""
    total_rounds: int = 0
    current_round: int = 0
    team_score: int = 0
    bot_score: int = 0
    bot_think_delay: float = 2.0
    answers: Dict[int, bool] = field(default_factory=dict)
    answer_options: Dict[int, str] = field(default_factory=dict)
    question_message_ids: Dict[int, int] = field(default_factory=dict)
    current_question: Dict[str, Any] | None = None
    jobs: Dict[str, Job] = field(default_factory=dict)
    dummy_mode: bool = False
    dummy_counter: int = 0
    remaining_pairs: List[Dict[str, Any]] = field(default_factory=list)
    current_pair: Dict[str, Any] | None = None
    turn_index: int = 0
    player_stats: Dict[int, int] = field(default_factory=dict)


@dataclass
class SprintResult:
    """Single sprint game result."""

    score: int
    total: int


@dataclass
class UserStats:
    """Aggregated per-user statistics kept in ``user_data``."""

    sprint_results: List[SprintResult] = field(default_factory=list)
    to_repeat: Set[str] = field(default_factory=set)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "sprint_results": [r.__dict__ for r in self.sprint_results],
            "to_repeat": list(self.to_repeat),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserStats":
        results = [SprintResult(**r) for r in data.get("sprint_results", [])]
        to_repeat = set(data.get("to_repeat", []))
        return cls(results, to_repeat)


def get_user_stats(user_data: Dict[str, Any]) -> UserStats:
    """Retrieve ``UserStats`` object from ``user_data`` creating if needed."""

    stats = user_data.get("stats")
    if isinstance(stats, UserStats):
        return stats
    if isinstance(stats, dict):
        stats = UserStats.from_dict(stats)
    else:
        stats = UserStats()
    user_data["stats"] = stats
    return stats


def record_sprint_result(user_data: Dict[str, Any], score: int, total: int) -> None:
    """Append a sprint result to ``user_data`` stats."""

    stats = get_user_stats(user_data)
    stats.sprint_results.append(SprintResult(score=score, total=total))


def add_to_repeat(user_data: Dict[str, Any], items: Iterable[str]) -> None:
    """Add flashcard items to the per-user repeat list."""

    stats = get_user_stats(user_data)
    stats.to_repeat.update(items)


class StatsStorage:
    """Optional JSON-based persistence for ``UserStats``."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> Dict[int, UserStats]:
        if not self.path.exists():
            return {}
        raw = orjson.loads(self.path.read_bytes())
        return {int(uid): UserStats.from_dict(data) for uid, data in raw.items()}

    def save(self, stats: Dict[int, UserStats]) -> None:
        raw = {str(uid): s.as_dict() for uid, s in stats.items()}
        self.path.write_bytes(orjson.dumps(raw))
