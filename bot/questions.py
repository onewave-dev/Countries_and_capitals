import random

from .state import DataSource
from .flags import get_country_flag


def pick_question(data: DataSource, continent: str | None, mode: str):
    """Generate a question based on the provided mode."""
    # mode: "country_to_capital" | "capital_to_country" | "mixed"
    countries = data.countries(continent)
    if not countries:
        raise RuntimeError("No countries for selected continent")

    country = random.choice(countries)
    capital = data.capital_by_country[country]

    question_type = mode
    if mode == "mixed":
        question_type = random.choice(["country_to_capital", "capital_to_country"])

    if question_type == "country_to_capital":
        correct = capital
        pool = [c for c in data.capitals(continent) if c != capital]
    else:
        correct = country
        pool = [c for c in countries if c != country]

    distractors = random.sample(pool, k=min(3, len(pool)))
    options = distractors + [correct]
    random.shuffle(options)

    if question_type == "country_to_capital":
        flag = get_country_flag(country)
        prompt = f"Какая столица у {flag} {country}?".strip()
    else:
        prompt = f"К какой стране относится {capital}?"
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


def make_card_question(data: DataSource, item: str, mode: str):
    """Return a flash-card style question for a specific item.

    ``item`` is either a country or a capital depending on ``mode``. For the
    mixed mode the direction is determined by the type of ``item`` itself.
    The returned dictionary mirrors :func:`pick_question` but without
    distractors.
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
    else:
        capital = item
        country = data.country_by_capital[capital]
        prompt = f"К какой стране относится {capital}?"
        answer = f"{get_country_flag(country)} {country}".strip()

    return {
        "type": question_type,
        "country": country,
        "capital": capital,
        "prompt": prompt,
        "answer": answer,
    }
