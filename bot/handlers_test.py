import asyncio
import random
import logging

from telegram import Update
from telegram.error import TelegramError, BadRequest
from telegram.ext import ContextTypes
from httpx import HTTPError

# ``DATA`` is loaded in ``app`` which requires TELEGRAM_BOT_TOKEN to be set.
# During unit tests this environment variable may be missing, so fall back to
# ``None`` to avoid import-time errors.
try:  # pragma: no cover - best effort for missing token during tests
    from app import DATA
except RuntimeError:  # pragma: no cover - token not set
    DATA = None  # type: ignore
from .state import TestSession
from .keyboards import (
    cards_kb,
    cards_answer_kb,
    back_to_menu_kb,
    continent_kb,
)
from .questions import make_card_question
from .flags import get_country_flag

logger = logging.getLogger(__name__)

__all__ = ("cb_test",)
__test__ = False


async def _next_question(
    update: Update, context: ContextTypes.DEFAULT_TYPE, replace_message: bool = True
) -> None:
    """Send the next test question or finish if queue is empty."""

    session: TestSession = context.user_data["test_session"]
    if not session.queue:
        await _finish_session(update, context)
        return

    country = session.queue.pop(0)
    direction = random.choice(["country_to_capital", "capital_to_country"])
    item = country if direction == "country_to_capital" else DATA.capital_by_country[country]
    question = make_card_question(DATA, item, direction)
    session.current = question
    session.stats["total"] += 1

    logger.debug(
        "Generated test question for user %s: %s -> %s",
        session.user_id,
        question["prompt"],
        question["answer"],
    )

    if update.callback_query and replace_message:
        q = update.callback_query
        try:
            await q.edit_message_text(
                question["prompt"],
                reply_markup=cards_kb(question["options"]),
                parse_mode="HTML",
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send test question: %s", e)
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
            logger.warning("Failed to send test question: %s", e)
            return


async def _finish_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Output final stats and unknown pairs."""

    session: TestSession | None = context.user_data.get("test_session")
    if not session:
        return

    text = f"{session.stats['correct']} правильных из {session.stats['total']}"
    if session.unknown_set:
        lines = []
        for country in sorted(session.unknown_set):
            capital = DATA.capital_by_country.get(country, "")
            flag = get_country_flag(country)
            lines.append(f"{flag} {country} — {capital}")
        text += "\n\nОшибки или пропуски:\n" + "\n".join(lines)
    chat_id = update.effective_chat.id
    try:
        await context.bot.send_message(chat_id, text, reply_markup=back_to_menu_kb())
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to send test results: %s", e)
    context.user_data.pop("test_session", None)


async def cb_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all ``^test:`` callbacks."""

    q = update.callback_query
    parts = q.data.split(":")

    if parts == ["test", "continent"]:
        await q.answer()
        await q.edit_message_text(
            "📝 Тест: выбери континент.",
            reply_markup=continent_kb("test", include_menu=True, include_world=False),
        )
        return

    if parts == ["test", "random30"]:
        await q.answer()
        countries = DATA.countries()
        queue = random.sample(countries, k=min(30, len(countries)))
        session = TestSession(user_id=update.effective_user.id, queue=queue)
        context.user_data["test_session"] = session
        await _next_question(update, context)
        return

    if len(parts) == 2 and parts[0] == "test" and parts[1] not in {
        "opt",
        "show",
        "skip",
        "next",
        "finish",
    }:
        await q.answer()
        continent = parts[1]
        queue = DATA.countries(continent)
        random.shuffle(queue)
        session = TestSession(user_id=update.effective_user.id, queue=queue)
        context.user_data["test_session"] = session
        await _next_question(update, context)
        return

    session: TestSession | None = context.user_data.get("test_session")
    if not session or not hasattr(session, "current"):
        await q.answer()
        try:
            await q.edit_message_text("Сессия не найдена", reply_markup=back_to_menu_kb())
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify missing session: %s", e)
        return

    current = session.current
    if parts[1] == "opt":
        await q.answer()
        index = int(parts[2])
        selected = current["options"][index]
        try:
            await q.edit_message_reply_markup(None)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to clear test buttons: %s", e)
        if selected == current["answer"]:
            session.stats["correct"] += 1
            text = "✅ Верно"
            if current["type"] == "country_to_capital":
                text += f"\n{current['country']}\nСтолица: {current['capital']}"
            else:
                text += f"\n{current['country']}"
        else:
            session.unknown_set.add(current["country"])
            text = (
                "❌ <b>Неверно</b>."
                f"\n\nПравильный ответ:\n<b>{current['answer']}</b>"
            )
        try:
            await context.bot.send_message(q.message.chat_id, text, parse_mode="HTML")
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send test feedback: %s", e)
        await asyncio.sleep(2)
        await _next_question(update, context, replace_message=False)
        return

    action = parts[1]
    if action == "show":
        await q.answer()
        session.unknown_set.add(current["country"])
        try:
            await q.edit_message_text(
                f"{current['prompt']}\n\n<b>Ответ: {current['answer']}</b>",
                parse_mode="HTML",
                reply_markup=cards_answer_kb(),
            )
        except BadRequest:
            logger.debug("Duplicate show answer for user %s", session.user_id)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to show test answer: %s", e)
        return

    if action == "next":
        await q.answer()
        await _next_question(update, context)
        return

    if action == "skip":
        await q.answer()
        session.unknown_set.add(current["country"])
        await _next_question(update, context)
        return

    if action == "finish":
        await q.answer()
        await _finish_session(update, context)
        return

    await q.answer()
