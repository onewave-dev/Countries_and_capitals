"""Handlers for the flash-cards training mode."""

import logging
import random
import asyncio
from typing import Optional

from telegram import Update
from telegram.error import TelegramError
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
    fact_more_kb,
)
from .flags import get_country_flag, get_flag_image_path
from .handlers_menu import WELCOME
from .facts import get_static_fact, generate_llm_fact


logger = logging.getLogger(__name__)


async def _next_card(
    update: Update, context: ContextTypes.DEFAULT_TYPE, replace_message: bool = True
) -> None:
    """Send the next card or finish the session if queue is empty.

    Parameters
    ----------
    update: Update
        The incoming update triggering the next card.
    context: ContextTypes.DEFAULT_TYPE
        The context provided by the handler.
    replace_message: bool, optional
        When ``True`` (default), the previous message with options is edited with
        the next question. When ``False``, the next question is sent as a new
        message instead of editing the existing one. This is used after sending
        feedback on a user's answer so that the feedback message is preserved.
        The final card in the queue is always sent as a new message.
    """

    session: CardSession = context.user_data["card_session"]
    if not session.queue:
        await _finish_session(update, context)
        return

    is_last = len(session.queue) == 1
    raw = session.queue.pop(0)
    if isinstance(raw, tuple):
        country, direction = raw
        item = (
            country
            if direction == "country_to_capital"
            else DATA.capital_by_country[country]
        )
    else:
        item = raw
        if raw in DATA.capital_by_country:
            direction = "country_to_capital"
        else:
            direction = "capital_to_country"
    question = make_card_question(
        DATA, item, direction, session.continent_filter
    )
    session.current = question  # dynamic attribute to store current card
    session.stats["shown"] += 1
    session.current_answered = False

    logger.debug(
        "Generated card question for user %s: %s -> %s",
        session.user_id,
        question["prompt"],
        question["answer"],
    )

    if update.callback_query and replace_message and not is_last:
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
        chat_id = update.effective_chat.id
        try:
            await context.bot.send_message(
                chat_id,
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
    if session.stats["known"] < session.stats["shown"]:
        if hasattr(session, "current") and not session.current_answered:
            item = (
                session.current["country"]
                if session.current["type"] == "country_to_capital"
                else session.current["capital"]
            )
            if item not in session.unknown_set:
                session.unknown_set.add(item)
                add_to_repeat(context.user_data, {item})
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

    chat_id = update.effective_chat.id
    try:
        await context.bot.send_message(chat_id, text, reply_markup=reply_markup)
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to send session results: %s", e)
        return


async def cb_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all ``^cards:`` callbacks."""

    q = update.callback_query

    parts = q.data.split(":")
    if parts == ["cards", "void"]:
        await q.answer()
        return
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
        if direction == "mixed":
            countries = DATA.countries(continent_filter)
            queue = [
                (c, random.choice(["country_to_capital", "capital_to_country"]))
                for c in countries
            ]
        else:
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
        await q.answer()
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
            fact = get_static_fact(current["country"])
            text = (
                f"✅ Верно\n{current['country']}"
                f"\nСтолица: {current['capital']}"
            )
            fact_msg = (
                f"{text}\n\n{fact}\n\nНажми кнопку ниже, чтобы узнать еще один факт"
            )
            flag_path = get_flag_image_path(current["country"])
            try:
                await q.edit_message_reply_markup(None)
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to clear card buttons: %s", e)
            msg = None
            if flag_path:
                try:
                    with flag_path.open("rb") as flag_file:
                        msg = await context.bot.send_photo(
                            q.message.chat_id,
                            flag_file,
                            caption=fact_msg,
                            reply_markup=fact_more_kb(),
                        )
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to send flag image: %s", e)
            else:
                try:
                    msg = await context.bot.send_message(
                        q.message.chat_id,
                        fact_msg,
                        reply_markup=fact_more_kb(),
                    )
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to send card feedback: %s", e)
            if msg:
                session.fact_message_id = msg.message_id
                session.fact_subject = current["country"]
                session.fact_text = fact
        else:
            session.unknown_set.add(item)
            add_to_repeat(context.user_data, {item})
            try:
                await q.edit_message_reply_markup(None)
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to clear card buttons: %s", e)
            try:
                await context.bot.send_message(
                    q.message.chat_id,
                    (
                        "❌ <b>Неверно</b>."
                        f"\n\nПравильный ответ:\n<b>{current['answer']}</b>"
                    ),
                    parse_mode="HTML",
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send card feedback: %s", e)
        session.current_answered = True
        await asyncio.sleep(3)
        await _next_card(update, context, replace_message=False)
        return

    action = parts[1]
    if action == "more_fact":
        await q.answer()
        if session.fact_message_id != q.message.message_id:
            return
        extra = await generate_llm_fact(
            session.fact_subject or "",
            session.fact_text or "",
        )
        base = q.message.caption or q.message.text or ""
        base = base.replace(
            "\n\nНажми кнопку ниже, чтобы узнать еще один факт", ""
        )
        try:
            if q.message.photo:
                await q.edit_message_caption(
                    caption=f"{base}\n\nЕще один факт: {extra}", reply_markup=None
                )
            else:
                await q.edit_message_text(
                    f"{base}\n\nЕще один факт: {extra}", reply_markup=None
                )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send extra fact: %s", e)
        session.fact_message_id = None
        return

    if action == "show":
        await q.answer()
        item = (
            current["country"]
            if current["type"] == "country_to_capital"
            else current["capital"]
        )
        session.unknown_set.add(item)
        add_to_repeat(context.user_data, {item})
        try:
            await q.edit_message_reply_markup(None)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to clear card buttons: %s", e)
        text = f"{current['country']}\nСтолица: {current['capital']}"
        fact = get_static_fact(current["country"])
        fact_msg = (
            f"{text}\n\n{fact}\n\nНажми кнопку ниже, чтобы узнать еще один факт"
        )
        flag_path = get_flag_image_path(current["country"])
        msg = None
        if flag_path:
            try:
                with flag_path.open("rb") as flag_file:
                    msg = await context.bot.send_photo(
                        q.message.chat_id,
                        flag_file,
                        caption=fact_msg,
                        reply_markup=fact_more_kb(),
                    )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send flag image: %s", e)
        else:
            try:
                msg = await context.bot.send_message(
                    q.message.chat_id,
                    fact_msg,
                    reply_markup=fact_more_kb(),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send card feedback: %s", e)
        if msg:
            session.fact_message_id = msg.message_id
            session.fact_subject = current["country"]
            session.fact_text = fact
        session.current_answered = True
        await asyncio.sleep(3)
        await _next_card(update, context, replace_message=False)
        return

    if action == "next":
        await q.answer()
        await _next_card(update, context)
        return

    if action == "skip":
        await q.answer()
        item = (
            current["country"]
            if current["type"] == "country_to_capital"
            else current["capital"]
        )
        session.unknown_set.add(item)
        add_to_repeat(context.user_data, {item})
        session.current_answered = True
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

