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


def cards_kb(options: list[str]) -> InlineKeyboardMarkup:
    """Keyboard for flash-card questions with answer options."""
    buttons = [
        InlineKeyboardButton(opt, callback_data=f"cards:opt:{i}")
        for i, opt in enumerate(options)
    ]
    rows = [buttons[:2]]
    if len(buttons) > 2:
        rows.append(buttons[2:4])
    rows.append([InlineKeyboardButton("Показать ответ", callback_data="cards:show")])
    rows.append([InlineKeyboardButton("Пропустить", callback_data="cards:skip")])
    rows.append([InlineKeyboardButton("Завершить", callback_data="cards:finish")])
    return InlineKeyboardMarkup(rows)


def cards_repeat_kb() -> InlineKeyboardMarkup:
    """Keyboard shown after session to repeat unknown cards."""
    rows = [
        [InlineKeyboardButton("Повторить", callback_data="cards:repeat")],
        [InlineKeyboardButton("Завершить", callback_data="cards:finish")],
    ]
    return InlineKeyboardMarkup(rows)


def sprint_kb(options: list[str], allow_skip: bool = True) -> InlineKeyboardMarkup:
    """Keyboard for sprint questions with four options and optional skip."""
    buttons = [
        InlineKeyboardButton(opt, callback_data=f"sprint:opt:{i}")
        for i, opt in enumerate(options)
    ]
    rows = [buttons[:2], buttons[2:4]]
    if allow_skip:
        rows.append([InlineKeyboardButton("Пропустить", callback_data="sprint:skip")])
    return InlineKeyboardMarkup(rows)


# ===== Cooperative mode keyboards =====


def coop_join_kb(session_id: str) -> InlineKeyboardMarkup:
    """Keyboard with a single join button for cooperative matches."""

    rows = [[InlineKeyboardButton("🙋 Участвовать", callback_data=f"coop:join:{session_id}")]]
    return InlineKeyboardMarkup(rows)


def coop_rounds_kb(session_id: str) -> InlineKeyboardMarkup:
    """Keyboard to select number of rounds."""

    rows = [
        [InlineKeyboardButton("5", callback_data=f"coop:rounds:{session_id}:5")],
        [InlineKeyboardButton("10", callback_data=f"coop:rounds:{session_id}:10")],
        [InlineKeyboardButton("15", callback_data=f"coop:rounds:{session_id}:15")],
    ]
    return InlineKeyboardMarkup(rows)


def coop_difficulty_kb(session_id: str) -> InlineKeyboardMarkup:
    """Keyboard to select bot difficulty."""

    rows = [
        [InlineKeyboardButton("🟢 Лёгкий", callback_data=f"coop:diff:{session_id}:easy")],
        [InlineKeyboardButton("🟡 Средний", callback_data=f"coop:diff:{session_id}:medium")],
        [InlineKeyboardButton("🔴 Сложный", callback_data=f"coop:diff:{session_id}:hard")],
    ]
    return InlineKeyboardMarkup(rows)


def coop_answer_kb(session_id: str, player_id: int, options: list[str]) -> InlineKeyboardMarkup:
    """Keyboard with four answer options bound to a player."""

    buttons = [
        InlineKeyboardButton(opt, callback_data=f"coop:ans:{session_id}:{player_id}:{i}")
        for i, opt in enumerate(options)
    ]
    rows = [buttons[:2], buttons[2:4]]
    return InlineKeyboardMarkup(rows)

