"""Utility helpers shared between training modes for subset selection."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from httpx import HTTPError

try:  # pragma: no cover - safeguard for tests without token
    from app import DATA
except RuntimeError:  # pragma: no cover
    DATA = None  # type: ignore

try:  # pragma: no cover - avoid hard dependency during tests
    from .handlers_menu import build_country_list_chunks
except (RuntimeError, ImportError):
    from .flags import get_country_flag

    def build_country_list_chunks(countries: list[str], title: str) -> list[str]:
        lines: list[str] = []
        for country in countries:
            capital = DATA.capital_by_country.get(country, "") if DATA else ""
            flag = get_country_flag(country)
            lines.append(f"{flag} {country} - Столица: {capital}")

        chunks: list[str] = []
        current = title
        for line in lines:
            line_text = f"{line}\n"
            if len(current) + len(line_text) > 4000:
                chunks.append(current.rstrip())
                current = line_text
            else:
                current += line_text
        chunks.append(current.rstrip())
        return chunks

logger = logging.getLogger(__name__)


def select_matching_countries(countries: Iterable[str]) -> set[str]:
    """Return countries whose capital matches the country name."""

    result: set[str] = set()
    for country in countries:
        capital = DATA.capital_by_country.get(country, "") if DATA else ""
        if capital and capital.casefold() == country.casefold():
            result.add(country)
    return result


def select_countries_by_letter(countries: Iterable[str], letter: str) -> set[str]:
    """Return countries whose capital starts with the provided ``letter``."""

    normalized = letter.strip()
    if len(normalized) != 1 or not normalized.isalpha():
        return set()

    normalized = normalized.casefold()
    result: set[str] = set()
    for country in countries:
        capital = DATA.capital_by_country.get(country, "").lstrip() if DATA else ""
        if not capital:
            continue
        first_char = capital[0].casefold()
        if first_char == normalized:
            result.add(country)
    return result


def select_remaining_countries(
    countries: Iterable[str], *exclude_groups: Iterable[str]
) -> set[str]:
    """Return countries that are not present in ``exclude_groups``."""

    excluded: set[str] = set()
    for group in exclude_groups:
        excluded.update(group)
    return set(countries) - excluded


def _prefixed(prefix: str, suffix: str) -> str:
    return f"{prefix}_{suffix}" if prefix else suffix


async def cleanup_preview_messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prefix: str,
    keep_message_id: Optional[int] = None,
) -> None:
    """Delete previously sent preview messages for the given ``prefix``."""

    key_messages = _prefixed(prefix, "preview_messages")
    key_chunks = _prefixed(prefix, "preview_chunks")
    message_ids: list[int] = context.user_data.pop(key_messages, [])
    context.user_data.pop(key_chunks, None)
    chat_id = update.effective_chat.id
    for message_id in message_ids:
        if keep_message_id is not None and message_id == keep_message_id:
            continue
        try:
            await context.bot.delete_message(chat_id, message_id)
        except (TelegramError, HTTPError) as exc:
            logger.debug("Failed to delete preview message %s: %s", message_id, exc)


async def show_preview(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    subset: Iterable[str],
    title: str,
    back_action: str,
    prefix: str,
    keyboard_factory: Callable[[str], InlineKeyboardMarkup],
    origin_message_id: Optional[int] = None,
) -> bool:
    """Display preview list of countries before starting the session."""

    countries = sorted(set(subset))
    if not countries:
        return False

    subset_key = _prefixed(prefix, "subset")
    chunks_key = _prefixed(prefix, "preview_chunks")
    messages_key = _prefixed(prefix, "preview_messages")
    letter_key = _prefixed(prefix, "letter_pending")

    context.user_data[subset_key] = countries
    chunks = build_country_list_chunks(countries, title)
    context.user_data[chunks_key] = chunks

    chat_id = update.effective_chat.id
    message_id = origin_message_id
    if message_id is None and update.callback_query:
        message_id = update.callback_query.message.message_id
    elif message_id is None and update.effective_message:
        message_id = update.effective_message.message_id

    preview_messages: list[int] = []

    try:
        if len(chunks) == 1:
            markup = keyboard_factory(back_action)
            if message_id is not None:
                msg = await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=chunks[0],
                    reply_markup=markup,
                )
                preview_messages.append(msg.message_id)
            else:
                msg = await context.bot.send_message(
                    chat_id,
                    chunks[0],
                    reply_markup=markup,
                )
                preview_messages.append(msg.message_id)
        else:
            if message_id is not None:
                msg = await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=chunks[0],
                )
                preview_messages.append(msg.message_id)
            else:
                msg = await context.bot.send_message(chat_id, chunks[0])
                preview_messages.append(msg.message_id)
            for chunk in chunks[1:-1]:
                sent = await context.bot.send_message(chat_id, chunk)
                preview_messages.append(sent.message_id)
            last = await context.bot.send_message(
                chat_id, chunks[-1], reply_markup=keyboard_factory(back_action)
            )
            preview_messages.append(last.message_id)
    except (TelegramError, HTTPError) as exc:
        logger.warning("Failed to display preview list: %s", exc)
        return False

    context.user_data[messages_key] = preview_messages
    context.user_data.pop(letter_key, None)
    return True
