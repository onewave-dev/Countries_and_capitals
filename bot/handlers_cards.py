"""Handlers for the flash-cards training mode."""

import logging
import random
from typing import Optional

from telegram import Update
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes
from httpx import HTTPError

from app import DATA
from .state import CardSession, add_to_repeat, get_user_stats
from .questions import make_card_question
from .keyboards import (
    cards_kb,
    cards_repeat_kb,
    cards_finish_kb,
    main_menu_kb,
    cards_answer_kb,
)
from .flags import get_country_flag
from .handlers_menu import WELCOME


logger = logging.getLogger(__name__)


async def _next_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the next card or finish the session if queue is empty."""

    session: CardSession = context.user_data["card_session"]
    if not session.queue:
        await _finish_session(update, context)
        return

    item = session.queue.pop(0)
    question = make_card_question(
        DATA, item, session.mode, session.continent_filter
    )
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
        try:
            await q.edit_message_text(
                question["prompt"],
                reply_markup=cards_kb(question["options"]),
                parse_mode="HTML",
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send card: %s", e)
            return
    else:
        try:
            await update.effective_message.reply_text(
                question["prompt"],
                reply_markup=cards_kb(question["options"]),
                parse_mode="HTML",
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send card: %s", e)
            return


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
    reply_markup = cards_finish_kb()
    if session.unknown_set:
        unknown_lines = []
        for item in sorted(session.unknown_set):
            if item in DATA.capital_by_country:
                country = item
                capital = DATA.capital_by_country[item]
            else:
                country = DATA.country_by_capital[item]
                capital = item
            flag = get_country_flag(country)
            pair = f"{flag} {country} — Столица: {capital}"
            unknown_lines.append(pair)
        text += "\nНеизвестные:\n" + "\n".join(unknown_lines)
        reply_markup = cards_repeat_kb()
    else:
        context.user_data.pop("card_session", None)

    if update.callback_query:
        q = update.callback_query
        try:
            await q.edit_message_text(text, reply_markup=reply_markup)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send session results: %s", e)
            return
    else:
        try:
            await update.effective_message.reply_text(text, reply_markup=reply_markup)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send session results: %s", e)
            return


async def cb_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all ``^cards:`` callbacks."""

    q = update.callback_query

    parts = q.data.split(":")
    if parts == ["cards", "menu"]:
        await q.answer()
        context.user_data.pop("card_session", None)
        try:
            await q.edit_message_text(WELCOME, reply_markup=main_menu_kb())
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to return to menu: %s", e)
        return
    if len(parts) == 3 and parts[1] != "opt":
        await q.answer()
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

    session: CardSession | None = context.user_data.get("card_session")
    if not session or not hasattr(session, "current"):
        await q.answer()
        try:
            await q.edit_message_text("Сессия не найдена")
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify missing session: %s", e)
        return

    current = session.current

    if len(parts) == 3 and parts[1] == "opt":
        index = int(parts[2])
        item = (
            current["country"]
            if current["type"] == "country_to_capital"
            else current["capital"]
        )
        selected = current["options"][index]
        if selected == current["answer"]:
            if item not in session.unknown_set:
                get_user_stats(context.user_data).to_repeat.discard(item)
                session.stats["known"] += 1
            await q.answer("✅ Верно", show_alert=True)
        else:
            session.unknown_set.add(item)
            add_to_repeat(context.user_data, {item})
            await q.answer(
                f"❌ Неверно.\nПравильный ответ:\n{current['answer']}",
                show_alert=True,
            )
        await _next_card(update, context)
        return

    action = parts[1]
    if action == "show":
        await q.answer()
        item = current["country"] if current["type"] == "country_to_capital" else current["capital"]
        session.unknown_set.add(item)
        add_to_repeat(context.user_data, {item})
        prompt_plain = current["prompt"].replace("<b>", "").replace("</b>", "")
        target_text_plain = f"{prompt_plain}\n\nОтвет: {current['answer']}"
        if q.message.text == target_text_plain:
            logger.debug("Skipping edit for user %s: answer already shown", session.user_id)
            return
        try:
            await q.edit_message_text(
                f"{current['prompt']}\n\n<b>Ответ: {current['answer']}</b>",
                parse_mode="HTML",
                reply_markup=cards_answer_kb(),
            )
        except BadRequest:
            logger.debug(
                "Ignoring BadRequest for duplicate edit for user %s", session.user_id
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to show answer: %s", e)
            return
        return

    if action == "next":
        await q.answer()
        await _next_card(update, context)
        return

    if action == "skip":
        await q.answer()
        item = current["country"] if current["type"] == "country_to_capital" else current["capital"]
        session.unknown_set.add(item)
        add_to_repeat(context.user_data, {item})
        session.queue.append(item)
        await _next_card(update, context)
        return

    if action == "finish":
        await q.answer()
        await _finish_session(update, context)
        return

    if action == "repeat" and session.unknown_set:
        await q.answer()
        session.queue = list(session.unknown_set)
        random.shuffle(session.queue)
        session.unknown_set.clear()
        session.stats = {"shown": 0, "known": 0}
        await _next_card(update, context)
        return

    await q.answer()

