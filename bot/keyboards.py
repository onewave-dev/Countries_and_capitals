"""Inline keyboards used across the bot menus."""

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import unicodedata


def wrap_button_text(text: str, limit: int = 20) -> str:
    """Insert line breaks so that each line is at most *limit* chars.

    If the text starts with an emoji (such as a country flag), the emoji and
    the first word are kept together before applying wrapping. This prevents
    splits like "🇨🇫\nЦентральноафриканская".
    """
    words = text.split()
    if not words:
        return text

    def _is_emoji(token: str) -> bool:
        return all(unicodedata.category(ch) == "So" for ch in token)

    if len(words) > 1 and _is_emoji(words[0]):
        words[0] = f"{words[0]} {words[1]}"
        del words[1]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return "\n".join(lines)


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
    "Австралия и Океания",
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


def sprint_duration_kb(continent: str) -> InlineKeyboardMarkup:
    """Keyboard for choosing sprint duration."""

    rows = [
        [InlineKeyboardButton("30 секунд", callback_data=f"sprint:{continent}:30")],
        [InlineKeyboardButton("60 секунд", callback_data=f"sprint:{continent}:60")],
        [InlineKeyboardButton("90 секунд", callback_data=f"sprint:{continent}:90")],
    ]
    return InlineKeyboardMarkup(rows)


def cards_kb(options: list[str]) -> InlineKeyboardMarkup:
    """Keyboard for flash-card questions with answer options."""
    wrapped = [wrap_button_text(opt) for opt in options]
    max_len = max(len(line) for opt in wrapped for line in opt.split("\n"))
    buttons = [
        InlineKeyboardButton(opt, callback_data=f"cards:opt:{i}")
        for i, opt in enumerate(wrapped)
    ]
    if max_len > 20:
        rows = [[btn] for btn in buttons]
    else:
        rows = [buttons[:2]]
        if len(buttons) > 2:
            rows.append(buttons[2:4])
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
    wrapped = [wrap_button_text(opt) for opt in options]
    max_len = max(len(line) for opt in wrapped for line in opt.split("\n"))
    buttons = [
        InlineKeyboardButton(opt, callback_data=f"sprint:opt:{i}")
        for i, opt in enumerate(wrapped)
    ]
    if max_len > 20:
        rows = [[btn] for btn in buttons]
    else:
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

    wrapped = [wrap_button_text(opt) for opt in options]
    max_len = max(len(line) for opt in wrapped for line in opt.split("\n"))
    buttons = [
        InlineKeyboardButton(opt, callback_data=f"coop:ans:{session_id}:{player_id}:{i}")
        for i, opt in enumerate(wrapped)
    ]
    if max_len > 20:
        rows = [[btn] for btn in buttons]
    else:
        rows = [buttons[:2], buttons[2:4]]
    return InlineKeyboardMarkup(rows)

