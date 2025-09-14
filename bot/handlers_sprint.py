"""Handlers for the sprint (time-based) game."""

import logging
import time
import asyncio

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from httpx import HTTPError

from app import DATA
from .state import SprintSession, record_sprint_result
from .questions import pick_question
from .flags import get_country_flag, get_flag_image_path
from .keyboards import sprint_kb, sprint_result_kb
from .handlers_menu import WELCOME, main_menu_kb


logger = logging.getLogger(__name__)


async def _ask_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    replace_message: bool = True,
) -> None:
    """Generate and send the next sprint question.

    Parameters
    ----------
    update: Update
        Incoming update.
    context: ContextTypes.DEFAULT_TYPE
        Handler context.
    replace_message: bool, optional
        When ``True`` (default) edits the previous message with the new question.
        When ``False`` the question is sent as a new message so that the prior
        feedback remains visible.
    """

    session: SprintSession = context.user_data["sprint_session"]
    question = pick_question(
        DATA, session.continent_filter, session.mode, session.asked_countries
    )
    session.current = question
    session.asked_countries.add(question["country"])

    allow_skip = context.user_data.get("sprint_allow_skip", True)
    reply_markup = sprint_kb(question["options"], allow_skip)

    if update.callback_query and replace_message:
        q = update.callback_query
        try:
            await q.edit_message_text(
                question["prompt"], reply_markup=reply_markup, parse_mode="HTML"
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send sprint question: %s", e)
            return
    else:
        chat_id = update.effective_chat.id
        try:
            await context.bot.send_message(
                chat_id,
                question["prompt"],
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send sprint question: %s", e)
            return


async def _sprint_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback fired when sprint timer expires."""

    user_id = context.job.data["user_id"]
    user_data = context.application.user_data.get(user_id, {})
    session: SprintSession | None = user_data.get("sprint_session")
    if not session:
        return

    logger.debug(
        "Sprint timer expired for user %s: score=%d questions=%d",
        user_id,
        session.score,
        session.questions_asked,
    )

    result_text = (
        f"⏱ Время вышло! Ваш результат: {session.score} правильных из {session.questions_asked}"
    )
    result_text += "\n\nЧто было неправильно или пропущено:"
    if session.wrong_answers:
        wrong_lines = [
            f"{get_country_flag(c)} {c} — Столица: {k}"
            for c, k in session.wrong_answers
        ]
        result_text += "\n" + "\n".join(wrong_lines)

    continent = session.continent_filter or "Весь мир"

    try:
        await context.bot.send_message(
            user_id,
            result_text,
            reply_markup=sprint_result_kb(continent),
        )
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to send sprint timeout message: %s", e)
        return

    record_sprint_result(user_data, session.score, session.questions_asked)

    user_data.pop("sprint_session", None)


async def cb_sprint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all ``^sprint:`` callbacks."""

    q = update.callback_query

    parts = q.data.split(":")
    action = parts[1]
    if action == "void":
        await q.answer()
        return
    if parts == ["sprint", "menu"]:
        await q.answer()
        context.user_data.pop("sprint_session", None)
        try:
            await q.edit_message_text(WELCOME, reply_markup=main_menu_kb())
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to return to menu: %s", e)
        return
    if action not in {"opt", "skip"}:
        await q.answer()
        # Session setup: sprint:<continent>
        continent = action
        duration = 60
        continent_filter: str | None = None if continent == "Весь мир" else continent
        session = SprintSession(
            user_id=update.effective_user.id,
            duration_sec=duration,
        )
        session.continent_filter = continent_filter
        session.mode = "mixed"
        context.user_data["sprint_session"] = session

        job = context.application.job_queue.run_once(
            _sprint_timeout,
            session.duration_sec,
            data={"user_id": session.user_id},
            name=f"sprint_timer_{session.user_id}",
        )
        session.start_ts = time.time()
        context.user_data["sprint_job"] = job
        logger.debug(
            "Sprint timer started for user %s: %d sec",
            session.user_id,
            session.duration_sec,
        )

        await _ask_question(update, context)
        return

    # Ongoing session actions
    session: SprintSession | None = context.user_data.get("sprint_session")
    if not session or not hasattr(session, "current"):
        await q.answer()
        try:
            await q.edit_message_text("Спринт не найден")
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify missing sprint: %s", e)
        return

    if action == "opt":
        idx = int(parts[2])
        option = session.current["options"][idx]
        session.questions_asked += 1
        if option == session.current["correct"]:
            session.score += 1
            await q.answer()
            text = f"✅ Верно\n{session.current['country']}"
            if session.current["type"] == "country_to_capital":
                text += f"\nСтолица: {session.current['capital']}"
            flag_path = get_flag_image_path(session.current["country"])
            try:
                await q.edit_message_reply_markup(None)
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to clear sprint buttons: %s", e)
            if flag_path:
                try:
                    with flag_path.open("rb") as f:
                        await context.bot.send_photo(
                            q.message.chat_id, f, caption=text
                        )
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to send sprint flag image: %s", e)
            else:
                try:
                    await context.bot.send_message(q.message.chat_id, text)
                except (TelegramError, HTTPError) as e:
                    logger.warning(
                        "Failed to send sprint correct message: %s", e
                    )
            logger.debug(
                "Sprint correct answer by user %s: score=%d questions=%d",
                session.user_id,
                session.score,
                session.questions_asked,
            )
        else:
            session.wrong_answers.append(
                (session.current["country"], session.current["capital"])
            )
            await q.answer()
            try:
                await q.edit_message_reply_markup(None)
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to clear sprint buttons: %s", e)
            try:
                await context.bot.send_message(
                    q.message.chat_id,
                    (
                        "❌ <b>Неверно</b>."
                        f"\n\nПравильный ответ:\n<b>{session.current['correct']}</b>"
                    ),
                    parse_mode="HTML",
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send sprint wrong message: %s", e)
            logger.debug(
                "Sprint wrong answer by user %s: score=%d questions=%d",
                session.user_id,
                session.score,
                session.questions_asked,
            )
        await asyncio.sleep(1)
        await _ask_question(update, context, replace_message=False)
        return

    if action == "skip":
        await q.answer()
        session.questions_asked += 1
        session.wrong_answers.append(
            (session.current["country"], session.current["capital"])
        )
        try:
            await q.edit_message_reply_markup(None)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to clear sprint buttons: %s", e)
        try:
            await context.bot.send_message(q.message.chat_id, "⏭ Пропуск")
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send sprint skip message: %s", e)
        logger.debug(
            "Sprint question skipped by user %s: score=%d questions=%d",
            session.user_id,
            session.score,
            session.questions_asked,
        )
        await asyncio.sleep(1)
        await _ask_question(update, context, replace_message=False)
        return

