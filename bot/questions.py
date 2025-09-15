import random

from .state import DataSource
from .flags import get_country_flag


def pick_question(
    data: DataSource,
    continent: str | None,
    mode: str,
    asked_countries: set[str] | None = None,
):
    """Generate a question based on the provided mode."""
    # ``mode``: internal question type ("country_to_capital", "capital_to_country" or "mixed" for random direction)
    countries = data.countries(continent)
    if asked_countries:
        countries = [c for c in countries if c not in asked_countries]
    if not countries:
        countries = data.countries(continent)
        if asked_countries is not None:
            asked_countries.clear()

    country = random.choice(countries)
    capital = data.capital_by_country[country]
    actual_continent = data.continent_of_country(country) or continent

    question_type = mode
    if mode == "mixed":
        question_type = random.choice(["country_to_capital", "capital_to_country"])

    if question_type == "country_to_capital":
        correct = capital
        pool = [c for c in data.capitals(actual_continent) if c != capital]
    else:
        correct = country
        pool = [c for c in data.countries(actual_continent) if c != country]

    distractors = random.sample(pool, k=min(3, len(pool)))
    options = distractors + [correct]
    random.shuffle(options)

    if question_type == "country_to_capital":
        flag = get_country_flag(country)
        prompt = f"Какая столица у {flag} {country}?".strip()
    else:
        prompt = f"Столицей какой страны является <b>{capital}</b>?"
        correct = f"{get_country_flag(correct)} {correct}".strip()
        options = [f"{get_country_flag(o)} {o}".strip() for o in options]

    return {
        "type": question_type,
        "country": country,
        "capital": capital,
        "prompt": prompt,
        "correct": correct,
        "options": options,
    }


def make_card_question(
    data: DataSource, item: str, mode: str, continent: str | None = None
):
    """Return a flash-card question with answer options.

    ``item`` is either a country or a capital depending on ``mode``. For the
    mixed mode the direction is determined by the type of ``item`` itself.
    The returned dictionary mirrors :func:`pick_question` but always includes
    an ``options`` list with the correct answer and random distractors from the
    same continent pool.
    """

    question_type = mode
    if mode == "mixed":
        question_type = (
            "country_to_capital" if item in data.capital_by_country else "capital_to_country"
        )

    if question_type == "country_to_capital":
        country = item
        capital = data.capital_by_country[country]
        flag = get_country_flag(country)
        prompt = f"Какая столица у {flag} {country}?".strip()
        answer = capital
        cont = data.continent_of_country(country) or continent
        pool = [c for c in data.capitals(cont) if c != capital]
        distractors = random.sample(pool, k=min(3, len(pool)))
        options = distractors + [capital]
        random.shuffle(options)
    else:
        capital = item
        country = data.country_by_capital[capital]
        prompt = f"Столицей какой страны является <b>{capital}</b>?"
        answer = f"{get_country_flag(country)} {country}".strip()
        cont = data.continent_of_country(country) or continent
        pool = [c for c in data.countries(cont) if c != country]
        distractors = random.sample(pool, k=min(3, len(pool)))
        options_raw = distractors + [country]
        options = [f"{get_country_flag(o)} {o}".strip() for o in options_raw]
        random.shuffle(options)

    return {
        "type": question_type,
        "country": country,
        "capital": capital,
        "prompt": prompt,
        "answer": answer,
        "options": options,
    }
