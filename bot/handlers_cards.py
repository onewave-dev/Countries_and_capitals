"""Placeholder handler for the flash cards game."""

from telegram import Update
from telegram.ext import ContextTypes

from app import DATA


async def cb_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``^cards:`` callbacks.

    Expected callback data: ``cards:<continent>:<direction>``.
    The selections are stored in ``user_data`` for future use.
    """

    q = update.callback_query
    await q.answer()
    try:
        _, continent, direction = q.data.split(":", 2)
    except ValueError:  # pragma: no cover - defensive
        continent = direction = ""

    context.user_data["continent"] = continent
    context.user_data["direction"] = direction

    await q.edit_message_text(
        f"Карточки: континент {continent or '—'}, режим {direction or '—'}."
    )
