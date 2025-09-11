"""Inline keyboards used across the bot menus."""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    """Top-level menu with three game modes."""
    rows = [
        [InlineKeyboardButton("📘 Флэш-карточки", callback_data="menu:cards")],
        [InlineKeyboardButton("⏱ Игра на время", callback_data="menu:sprint")],
        [InlineKeyboardButton("🤝 Дуэт против Бота", callback_data="menu:coop")],
    ]
    return InlineKeyboardMarkup(rows)


CONTINENTS = [
    "Европа",
    "Азия",
    "Африка",
    "Северная Америка",
    "Южная Америка",
    "Океания",
    "Весь мир",
]


def continent_kb(prefix: str) -> InlineKeyboardMarkup:
    """Keyboard for choosing a continent.

    ``prefix`` should be ``menu:cards`` or ``menu:sprint`` so that callback data
    stays within the ``^menu:`` namespace while the user makes selections.
    """

    rows = [[InlineKeyboardButton(c, callback_data=f"{prefix}:{c}")] for c in CONTINENTS]
    return InlineKeyboardMarkup(rows)


def direction_kb(prefix: str, continent: str) -> InlineKeyboardMarkup:
    """Keyboard for choosing question direction.

    ``prefix`` is the final namespace (``cards`` or ``sprint``) so that pressing
    a button dispatches to the respective handler via ``^cards:``/``^sprint:``.
    """

    rows = [
        [
            InlineKeyboardButton(
                "Страна → столица",
                callback_data=f"{prefix}:{continent}:country_to_capital",
            )
        ],
        [
            InlineKeyboardButton(
                "Столица → страна",
                callback_data=f"{prefix}:{continent}:capital_to_country",
            )
        ],
        [
            InlineKeyboardButton(
                "Смешанный",
                callback_data=f"{prefix}:{continent}:mixed",
            )
        ],
    ]
    return InlineKeyboardMarkup(rows)


def cards_kb() -> InlineKeyboardMarkup:
    """Controls for a flash-card question."""
    rows = [
        [InlineKeyboardButton("Показать ответ", callback_data="cards:show")],
        [
            InlineKeyboardButton("✅ Знаю", callback_data="cards:know"),
            InlineKeyboardButton("❌ Не знаю", callback_data="cards:dont"),
        ],
        [InlineKeyboardButton("Пропустить", callback_data="cards:skip")],
        [InlineKeyboardButton("Завершить", callback_data="cards:finish")],
    ]
    return InlineKeyboardMarkup(rows)


def cards_repeat_kb() -> InlineKeyboardMarkup:
    """Keyboard shown after session to repeat unknown cards."""
    rows = [
        [InlineKeyboardButton("Повторить", callback_data="cards:repeat")],
        [InlineKeyboardButton("Завершить", callback_data="cards:finish")],
    ]
    return InlineKeyboardMarkup(rows)

