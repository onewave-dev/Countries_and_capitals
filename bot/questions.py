import random
from typing import Any, Dict

def pick_question(data: Dict[str, Any], continent: str | None, mode: str):
    # mode: "country_to_capital" | "capital_to_country" | "mixed"
    countries = []
    if continent and continent in data["countries_by_continent"]:
        countries = data["countries_by_continent"][continent]
    else:
        # объединяем все
        seen = set()
        for v in data["countries_by_continent"].values():
            for c in v:
                seen.add(c)
        countries = list(seen)

    if not countries:
        raise RuntimeError("No countries for selected continent")

    country = random.choice(countries)
    capital = data["capital_by_country"][country]

    question_type = mode
    if mode == "mixed":
        question_type = random.choice(["country_to_capital", "capital_to_country"])

    if question_type == "country_to_capital":
        correct = capital
        # отвлекающие — другие столицы из пула
        pool = [data["capital_by_country"][c] for c in countries if c != country]
    else:
        correct = country
        pool = [c for c in countries if c != country]

    distractors = random.sample(pool, k=min(3, len(pool)))
    options = distractors + [correct]
    random.shuffle(options)

    if question_type == "country_to_capital":
        prompt = f"Какая столица у {country}?"
    else:
        prompt = f"К какой стране относится {capital}?"

    return {
        "type": question_type,
        "country": country,
        "capital": capital,
        "prompt": prompt,
        "correct": correct,
        "options": options
    }
