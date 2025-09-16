"""Inline keyboards used across the bot menus."""

from inspect import signature
from textwrap import shorten
from unicodedata import east_asian_width

import telegram
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Text longer than this will be placed on its own row instead of pairing.
LONG_OPTION = 15
# Width of section headings like "ОБУЧЕНИЕ" surrounded by lines.  The value is
# used as a fallback when no dynamic width is supplied.
SECTION_WIDTH = 36
LINE_CHAR = "─"
SPACER = LINE_CHAR * 12
COOP_INVITE_REQUEST_ID = 1001

KeyboardButtonRequestUser = getattr(
    telegram,
    "KeyboardButtonRequestUser",
    telegram.KeyboardButtonRequestUsers,
)

_COOP_INVITE_REQUEST_PARAM = (
    "request_users"
    if "request_users" in signature(KeyboardButton).parameters
    else "request_user"
)
# Name of the ``KeyboardButton`` argument used to request users.  ``request_users``
# is only available starting from python-telegram-bot v21, while older releases
# expose the singular ``request_user``.


def _visible_len(text: str) -> int:
    """Approximate visual width of ``text`` in monospace cells.

    Emoji and other wide characters often take two cells on desktop Telegram
    clients.  ``east_asian_width`` classifies such characters as *Wide* or
    *Fullwidth*, allowing us to better balance decorative headings so that
    they appear centered both on mobile and desktop.
    """

    width = 0
    for ch in text:
        width += 2 if east_asian_width(ch) in {"F", "W"} else 1
    return width


def _section_heading(text: str, width: int = SECTION_WIDTH) -> str:
    """Return ``text`` centered with dashes filling the given ``width``.

    Two extra spaces are added on both sides of ``text`` so that the visual
    length of the resulting string stays consistent between different
    headings.
    """

    label = f"  {text}  "
    pad = max(width - _visible_len(label), 0)
    left = pad // 2
    right = pad - left
    return f"{LINE_CHAR * left}{label}{LINE_CHAR * right}"


def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Top-level menu with learning modes and games.

    Parameters
    ----------
    is_admin: bool, optional
        When ``True`` an additional admin-only test button is appended to the
        games section.
    """

    options = [
        ("📘 Флэш-карточки", "menu:cards"),
        ("📋 Учить по спискам", "menu:list"),
        ("📝 Тест", "menu:test"),
        ("⏱ Игра на время", "menu:sprint"),
        ("🤝 Дуэт против Бота", "menu:coop"),
    ]
    if is_admin:
        options.append(("[адм.]\u202fТестовая игра", "menu:coop_admin"))

    # Determine the maximum visual width among option labels to balance the
    # decorative section headings.  Add four characters for the extra spacing
    # around the heading text and ensure the width is even so that padding is
    # symmetrical.
    width = max(_visible_len(label) for label, _ in options) + 4
    if width % 2:
        width += 1

    rows = [
        [InlineKeyboardButton(_section_heading("ОБУЧЕНИЕ", width), callback_data="menu:void")]
    ]
    for label, data in options[:3]:
        rows.append([InlineKeyboardButton(label, callback_data=data)])
    rows.append([InlineKeyboardButton(_section_heading("ИГРЫ", width), callback_data="menu:void")])
    for label, data in options[3:]:
        rows.append([InlineKeyboardButton(label, callback_data=data)])
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


def continent_kb(
    prefix: str, include_menu: bool = False, include_world: bool = True
) -> InlineKeyboardMarkup:
    """Keyboard for choosing a continent.

    ``prefix`` should be ``menu:cards`` or ``menu:sprint`` so that callback data
    stays within the ``^menu:`` namespace while the user makes selections.
    ``include_menu`` optionally appends a button back to the main menu. Set
    ``include_world`` to ``False`` to hide the "Весь мир" option.
    """

    continents = CONTINENTS if include_world else [c for c in CONTINENTS if c != "Весь мир"]
    rows = [[InlineKeyboardButton(c, callback_data=f"{prefix}:{c}")] for c in continents]
    if include_menu:
        rows.append([InlineKeyboardButton("В меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def test_start_kb() -> InlineKeyboardMarkup:
    """Keyboard for starting the test mode."""

    rows = [
        [InlineKeyboardButton("Тестировать континент", callback_data="test:continent")],
        [InlineKeyboardButton("Тестировать 30 случайных", callback_data="test:random30")],
        [InlineKeyboardButton("В меню", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


def back_to_menu_kb() -> InlineKeyboardMarkup:
    """Keyboard with a single button that returns to the main menu."""

    rows = [[InlineKeyboardButton("В меню", callback_data="menu:main")]]
    return InlineKeyboardMarkup(rows)


def sprint_start_kb(continent: str) -> InlineKeyboardMarkup:
    """Keyboard with a single start button for the sprint."""

    rows = [[InlineKeyboardButton("Поехали!", callback_data=f"sprint:{continent}")]]
    return InlineKeyboardMarkup(rows)


def cards_kb(options: list[str], prefix: str = "cards") -> InlineKeyboardMarkup:
    """Keyboard for flash-card questions with answer options.

    ``prefix`` determines the callback namespace.  By default the regular
    ``cards`` prefix is used, but alternative prefixes (e.g. ``test``) can be
    supplied for other handlers.
    """

    rows: list[list[InlineKeyboardButton]] = []
    buffer: list[InlineKeyboardButton] = []
    for i, opt in enumerate(options):
        text = shorten(opt, width=40, placeholder="")
        btn = InlineKeyboardButton(text, callback_data=f"{prefix}:opt:{i}")
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

    rows.append([InlineKeyboardButton(SPACER, callback_data=f"{prefix}:void")])
    rows.append([InlineKeyboardButton("Показать ответ", callback_data=f"{prefix}:show")])
    rows.append([InlineKeyboardButton("Пропустить", callback_data=f"{prefix}:skip")])
    rows.append([InlineKeyboardButton("Завершить", callback_data=f"{prefix}:finish")])
    return InlineKeyboardMarkup(rows)


def cards_answer_kb(prefix: str = "cards") -> InlineKeyboardMarkup:
    """Keyboard shown after revealing the answer.

    ``prefix`` allows reuse of this keyboard in different callback namespaces.
    """
    rows = [
        [InlineKeyboardButton("Продолжить", callback_data=f"{prefix}:next")],
        [InlineKeyboardButton("Завершить", callback_data=f"{prefix}:finish")],
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
    # spacer row to visually separate options from action buttons
    rows.append([InlineKeyboardButton(SPACER, callback_data="sprint:void")])
    if allow_skip:
        rows.append([InlineKeyboardButton("Пропустить", callback_data="sprint:skip")])
    rows.append([InlineKeyboardButton("Прервать игру", callback_data="sprint:stop")])
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


def coop_admin_kb() -> InlineKeyboardMarkup:
    """Admin-only keyboard with a test match button."""

    rows = [
        [InlineKeyboardButton("[адм.]\u202fТестовая игра", callback_data="coop:test")],
        [InlineKeyboardButton("В меню", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(rows)


def coop_invite_kb() -> ReplyKeyboardMarkup:
    """Keyboard for inviting the second player."""

    request_kwargs = {
        _COOP_INVITE_REQUEST_PARAM: KeyboardButtonRequestUser(
            request_id=COOP_INVITE_REQUEST_ID,
            user_is_bot=False,
        )
    }
    rows = [
        [
            KeyboardButton(
                "Пригласить из контактов",
                **request_kwargs,
            )
        ],
        [KeyboardButton("Создать ссылку")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def coop_rounds_kb(session_id: str, player_id: int) -> InlineKeyboardMarkup:
    """Keyboard to select number of rounds."""

    rows = [
        [
            InlineKeyboardButton(
                "5", callback_data=f"coop:rounds:{session_id}:{player_id}:5"
            )
        ],
        [
            InlineKeyboardButton(
                "10", callback_data=f"coop:rounds:{session_id}:{player_id}:10"
            )
        ],
        [
            InlineKeyboardButton(
                "15", callback_data=f"coop:rounds:{session_id}:{player_id}:15"
            )
        ],
    ]
    return InlineKeyboardMarkup(rows)


def coop_difficulty_kb(session_id: str, player_id: int) -> InlineKeyboardMarkup:
    """Keyboard to select bot difficulty."""

    rows = [
        [
            InlineKeyboardButton(
                "🟢 Лёгкий · 70 %",
                callback_data=f"coop:diff:{session_id}:{player_id}:easy",
            )
        ],
        [
            InlineKeyboardButton(
                "🟡 Средний · 80 %",
                callback_data=f"coop:diff:{session_id}:{player_id}:medium",
            )
        ],
        [
            InlineKeyboardButton(
                "🔴 Продвинутый · 90 %",
                callback_data=f"coop:diff:{session_id}:{player_id}:hard",
            )
        ],
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


def coop_fact_more_kb(session_id: str) -> InlineKeyboardMarkup:
    """Keyboard with a button to request another fact."""

    rows = [[InlineKeyboardButton("Еще один факт", callback_data=f"coop:more_fact:{session_id}")]]
    return InlineKeyboardMarkup(rows)


def coop_finish_kb() -> InlineKeyboardMarkup:
    """Keyboard shown after a cooperative match finishes."""

    rows = [
        [InlineKeyboardButton("Сыграть еще раз", callback_data="menu:coop")],
        [InlineKeyboardButton("В меню", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(rows)

