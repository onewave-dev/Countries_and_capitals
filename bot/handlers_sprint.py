"""Placeholder handler for the sprint game."""

from telegram import Update
from telegram.ext import ContextTypes

from app import DATA


async def cb_sprint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``^sprint:`` callbacks.

    Expected callback data: ``sprint:<continent>:<direction>`` where ``direction``
    corresponds to question direction. Selections are stored in ``user_data``.
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
        f"Спринт: континент {continent or '—'}, режим {direction or '—'}."
    )
