"""Handlers for the sprint (time-based) game."""

import logging
import time

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from httpx import HTTPError

from app import DATA
from .state import SprintSession, record_sprint_result
from .questions import pick_question
from .keyboards import sprint_kb


logger = logging.getLogger(__name__)


async def _ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send the next sprint question."""

    session: SprintSession = context.user_data["sprint_session"]
    question = pick_question(DATA, session.continent_filter, session.mode)
    session.current = question

    allow_skip = context.user_data.get("sprint_allow_skip", True)
    reply_markup = sprint_kb(question["options"], allow_skip)

    if update.callback_query:
        q = update.callback_query
        try:
            await q.edit_message_text(
                question["prompt"], reply_markup=reply_markup, parse_mode="HTML"
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send sprint question: %s", e)
            return
    else:
        try:
            await update.effective_message.reply_text(
                question["prompt"], reply_markup=reply_markup, parse_mode="HTML"
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

    try:
        await context.bot.send_message(
            user_id,
            f"⏱ Время вышло! Ваш результат: {session.score} правильных из {session.questions_asked}",
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
    if action not in {"opt", "skip"}:
        await q.answer()
        # Session setup: sprint:<continent>:<duration>
        continent = action
        duration = int(parts[2]) if len(parts) > 2 else 60
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
            await q.answer("✅ Верно", show_alert=True)
            logger.debug(
                "Sprint correct answer by user %s: score=%d questions=%d",
                session.user_id,
                session.score,
                session.questions_asked,
            )
        else:
            await q.answer(
                f"❌ Неверно.\nПравильный ответ:\n{session.current['correct']}",
                show_alert=True,
            )
            logger.debug(
                "Sprint wrong answer by user %s: score=%d questions=%d",
                session.user_id,
                session.score,
                session.questions_asked,
            )
        await _ask_question(update, context)
        return

    if action == "skip":
        await q.answer()
        session.questions_asked += 1
        logger.debug(
            "Sprint question skipped by user %s: score=%d questions=%d",
            session.user_id,
            session.score,
            session.questions_asked,
        )
        await _ask_question(update, context)
        return

