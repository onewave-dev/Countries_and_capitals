"""Inline keyboards used across the bot menus."""

from textwrap import shorten
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Text longer than this will be placed on its own row instead of pairing.
LONG_OPTION = 15
# Separator line between answer options and other buttons.
SPACER = "────────────"


def main_menu_kb() -> InlineKeyboardMarkup:
    """Top-level menu with four learning modes."""
    rows = [
        [InlineKeyboardButton("📘 Флэш-карточки", callback_data="menu:cards")],
        [InlineKeyboardButton("⏱ Игра на время", callback_data="menu:sprint")],
        [InlineKeyboardButton("🤝 Дуэт против Бота", callback_data="menu:coop")],
        [InlineKeyboardButton("📋 Учить по списку стран", callback_data="menu:list")],
    ]
    return InlineKeyboardMarkup(rows)


CONTINENTS = [
    "Европа",
    "Азия",
    "Африка",
    "Северная Америка",
    "Южная Америка",
    "Австралия и Океания",
    "Весь мир",
]


def continent_kb(prefix: str, include_menu: bool = False) -> InlineKeyboardMarkup:
    """Keyboard for choosing a continent.

    ``prefix`` should be ``menu:cards`` or ``menu:sprint`` so that callback data
    stays within the ``^menu:`` namespace while the user makes selections.
    ``include_menu`` optionally appends a button back to the main menu.
    """

    rows = [[InlineKeyboardButton(c, callback_data=f"{prefix}:{c}")] for c in CONTINENTS]
    if include_menu:
        rows.append([InlineKeyboardButton("В меню", callback_data="menu:main")])
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


def sprint_start_kb(continent: str) -> InlineKeyboardMarkup:
    """Keyboard with a single start button for the sprint."""

    rows = [[InlineKeyboardButton("Поехали!", callback_data=f"sprint:{continent}")]]
    return InlineKeyboardMarkup(rows)


def cards_kb(options: list[str]) -> InlineKeyboardMarkup:
    """Keyboard for flash-card questions with answer options."""

    rows: list[list[InlineKeyboardButton]] = []
    buffer: list[InlineKeyboardButton] = []
    for i, opt in enumerate(options):
        text = shorten(opt, width=40, placeholder="")
        btn = InlineKeyboardButton(text, callback_data=f"cards:opt:{i}")
        if len(text) > LONG_OPTION:
            if buffer:
                rows.append(buffer)
                buffer = []
            rows.append([btn])
        else:
            buffer.append(btn)
            if len(buffer) == 2:
                rows.append(buffer)
                buffer = []
    if buffer:
        rows.append(buffer)
    # spacer row to visually separate options from action buttons

    rows.append([InlineKeyboardButton(SPACER, callback_data="cards:void")])
    rows.append([InlineKeyboardButton("Показать ответ", callback_data="cards:show")])
    rows.append([InlineKeyboardButton("Пропустить", callback_data="cards:skip")])
    rows.append([InlineKeyboardButton("Завершить", callback_data="cards:finish")])
    return InlineKeyboardMarkup(rows)


def cards_answer_kb() -> InlineKeyboardMarkup:
    """Keyboard shown after revealing the answer."""
    rows = [
        [InlineKeyboardButton("Продолжить", callback_data="cards:next")],
        [InlineKeyboardButton("Завершить", callback_data="cards:finish")],
    ]
    return InlineKeyboardMarkup(rows)


def fact_more_kb() -> InlineKeyboardMarkup:
    """Keyboard with a single button to request another fact."""
    rows = [[InlineKeyboardButton("Еще один факт", callback_data="cards:more_fact")]]
    return InlineKeyboardMarkup(rows)


def cards_repeat_kb() -> InlineKeyboardMarkup:
    """Keyboard shown after session to repeat unknown cards."""
    rows = [
        [InlineKeyboardButton("Повторить", callback_data="cards:repeat")],
        [InlineKeyboardButton("В меню", callback_data="cards:menu")],
    ]
    return InlineKeyboardMarkup(rows)


def cards_finish_kb() -> InlineKeyboardMarkup:
    """Keyboard shown after session with no unknown cards."""
    rows = [[InlineKeyboardButton("В меню", callback_data="cards:menu")]]
    return InlineKeyboardMarkup(rows)


def sprint_kb(options: list[str], allow_skip: bool = True) -> InlineKeyboardMarkup:
    """Keyboard for sprint questions with four options and optional skip."""

    rows: list[list[InlineKeyboardButton]] = []
    buffer: list[InlineKeyboardButton] = []
    for i, opt in enumerate(options):
        text = shorten(opt, width=40, placeholder="")
        btn = InlineKeyboardButton(text, callback_data=f"sprint:opt:{i}")
        if len(text) > LONG_OPTION:
            if buffer:
                rows.append(buffer)
                buffer = []
            rows.append([btn])
        else:
            buffer.append(btn)
            if len(buffer) == 2:
                rows.append(buffer)
                buffer = []
    if buffer:
        rows.append(buffer)
    if allow_skip:
        rows.append([InlineKeyboardButton(SPACER, callback_data="sprint:void")])
        rows.append([InlineKeyboardButton("Пропустить", callback_data="sprint:skip")])
    return InlineKeyboardMarkup(rows)


def sprint_result_kb(continent: str) -> InlineKeyboardMarkup:
    """Keyboard shown after sprint results.

    Provides a quick restart for the same continent and a button to return to
    the main menu.
    """

    rows = [
        [InlineKeyboardButton("Играть еще раз", callback_data=f"sprint:{continent}")],
        [InlineKeyboardButton("В меню", callback_data="sprint:menu")],
    ]
    return InlineKeyboardMarkup(rows)


def list_result_kb() -> InlineKeyboardMarkup:
    """Keyboard shown after displaying countries list."""

    rows = [
        [InlineKeyboardButton("Другой континент", callback_data="menu:list")],
        [InlineKeyboardButton("В меню", callback_data="menu:main")],
    ]
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


def coop_continent_kb(session_id: str) -> InlineKeyboardMarkup:
    """Keyboard to select continent for cooperative mode."""

    rows = [
        [InlineKeyboardButton(c, callback_data=f"coop:cont:{session_id}:{c}")]
        for c in CONTINENTS
    ]
    return InlineKeyboardMarkup(rows)


def coop_answer_kb(session_id: str, player_id: int, options: list[str]) -> InlineKeyboardMarkup:
    """Keyboard with four answer options bound to a player."""

    rows: list[list[InlineKeyboardButton]] = []
    buffer: list[InlineKeyboardButton] = []
    for i, opt in enumerate(options):
        text = shorten(opt, width=40, placeholder="")
        btn = InlineKeyboardButton(
            text, callback_data=f"coop:ans:{session_id}:{player_id}:{i}"
        )
        if len(text) > LONG_OPTION:
            if buffer:
                rows.append(buffer)
                buffer = []
            rows.append([btn])
        else:
            buffer.append(btn)
            if len(buffer) == 2:
                rows.append(buffer)
                buffer = []
    if buffer:
        rows.append(buffer)
    return InlineKeyboardMarkup(rows)

