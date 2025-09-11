"""Handlers for the flash-cards training mode."""

import logging
import random
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from app import DATA
from .state import CardSession, add_to_repeat, get_user_stats
from .questions import make_card_question
from .keyboards import cards_kb, cards_repeat_kb
from .flags import get_country_flag


logger = logging.getLogger(__name__)


async def _next_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the next card or finish the session if queue is empty."""

    session: CardSession = context.user_data["card_session"]
    if not session.queue:
        await _finish_session(update, context)
        return

    item = session.queue.pop(0)
    question = make_card_question(DATA, item, session.mode)
    session.current = question  # dynamic attribute to store current card
    session.stats["shown"] += 1

    logger.debug(
        "Generated card question for user %s: %s -> %s",
        session.user_id,
        question["prompt"],
        question["answer"],
    )

    if update.callback_query:
        q = update.callback_query
        await q.edit_message_text(question["prompt"], reply_markup=cards_kb())
    else:
        await update.effective_message.reply_text(
            question["prompt"], reply_markup=cards_kb()
        )


async def _finish_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Output final stats and unknown items."""

    session: CardSession | None = context.user_data.get("card_session")
    if not session:
        return

    logger.debug(
        "Card session finished for user %s: stats=%s unknown=%d",
        session.user_id,
        session.stats,
        len(session.unknown_set),
    )

    text = (
        f"Сессия завершена. Показано: {session.stats['shown']}, "
        f"знаю: {session.stats['known']}."
    )
    reply_markup = None
    if session.unknown_set:
        unknown_lines = []
        for item in sorted(session.unknown_set):
            if item in DATA.capital_by_country:
                flag = get_country_flag(item)
                pair = f"{flag} {item} — {DATA.capital_by_country[item]}".strip()
            else:
                country = DATA.country_by_capital[item]
                flag = get_country_flag(country)
                pair = f"{item} — {flag} {country}".strip()
            unknown_lines.append(pair)
        text += "\nНеизвестные:\n" + "\n".join(unknown_lines)
        reply_markup = cards_repeat_kb()
    else:
        context.user_data.pop("card_session", None)

    if update.callback_query:
        q = update.callback_query
        await q.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.effective_message.reply_text(text, reply_markup=reply_markup)


async def cb_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all ``^cards:`` callbacks."""

    q = update.callback_query
    await q.answer()

    parts = q.data.split(":")
    if len(parts) == 3:
        # Session setup: cards:<continent>:<direction>
        _, continent, direction = parts
        continent_filter: Optional[str] = None if continent == "Весь мир" else continent
        queue = DATA.items(continent_filter, direction)
        random.shuffle(queue)
        session = CardSession(
            user_id=update.effective_user.id,
            continent_filter=continent_filter,
            mode=direction,
            queue=queue,
        )
        context.user_data["card_session"] = session
        logger.debug(
            "Card session started for user %s: continent=%s mode=%s total=%d",
            session.user_id,
            continent_filter,
            direction,
            len(queue),
        )
        await _next_card(update, context)
        return

    # Ongoing session actions
    action = parts[1]
    session: CardSession | None = context.user_data.get("card_session")
    if not session or not hasattr(session, "current"):
        await q.edit_message_text("Сессия не найдена")
        return

    current = session.current
    if action == "show":
        await q.edit_message_text(
            f"{current['prompt']}\n\n<b>{current['answer']}</b>",
            parse_mode="HTML",
            reply_markup=cards_kb(),
        )
        return

    if action == "know":
        item = (
            current["country"]
            if current["type"] == "country_to_capital"
            else current["capital"]
        )
        get_user_stats(context.user_data).to_repeat.discard(item)
        session.stats["known"] += 1
        await _next_card(update, context)
        return

    if action == "dont":
        item = (
            current["country"]
            if current["type"] == "country_to_capital"
            else current["capital"]
        )
        session.unknown_set.add(item)
        add_to_repeat(context.user_data, {item})
        await _next_card(update, context)
        return

    if action == "skip":
        item = current["country"] if current["type"] == "country_to_capital" else current["capital"]
        session.queue.append(item)
        await _next_card(update, context)
        return

    if action == "finish":
        await _finish_session(update, context)
        context.user_data.pop("card_session", None)
        return

    if action == "repeat" and session.unknown_set:
        session.queue = list(session.unknown_set)
        random.shuffle(session.queue)
        session.unknown_set.clear()
        session.stats = {"shown": 0, "known": 0}
        await _next_card(update, context)
        return

    await q.answer()

