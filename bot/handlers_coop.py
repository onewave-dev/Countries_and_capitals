"""Handlers for the cooperative two-vs-bot mode via direct messages."""

from __future__ import annotations

import os
import random
import uuid
import logging
from typing import Dict, Tuple

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from httpx import HTTPError

from app import DATA
from .state import CoopSession
from .questions import pick_question
from .keyboards import (
    coop_answer_kb,
    coop_invite_kb,
    coop_rounds_kb,
    coop_difficulty_kb,
)
from .flags import get_flag_image_path


ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

logger = logging.getLogger(__name__)


# ===== Helpers =====


def _get_sessions(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, CoopSession]:
    """Return the global coop sessions mapping."""

    return context.application.bot_data.setdefault("coop_sessions", {})  # type: ignore[arg-type]


def _find_user_session(
    sessions: Dict[str, CoopSession], user_id: int
) -> Tuple[str, CoopSession] | tuple[None, None]:
    for sid, sess in sessions.items():
        if user_id in sess.players:
            return sid, sess
    return None, None


async def _start_round(context: ContextTypes.DEFAULT_TYPE, session: CoopSession) -> None:
    """Generate question and send it to the current player only."""

    question = pick_question(DATA, session.continent_filter, session.mode)
    session.current_question = question
    session.answers.clear()
    session.answer_options.clear()
    session.question_message_ids.clear()
    session.current_turn_index = 0

    current_player = session.players[session.current_turn_index]
    current_chat = session.player_chats[current_player]
    try:
        msg = await context.bot.send_message(
            current_chat,
            f"Раунд {session.current_round}/{session.total_rounds}\n{question['prompt']}",
            reply_markup=coop_answer_kb(
                session.session_id, current_player, question["options"]
            ),
            parse_mode="HTML",
        )
        session.question_message_ids[current_player] = msg.message_id
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to send coop question: %s", e)

    waiting_text = "Ожидаем ход другого игрока."
    for idx, pid in enumerate(session.players):
        if idx == session.current_turn_index:
            continue
        chat_id = session.player_chats[pid]
        try:
            await context.bot.send_message(
                chat_id,
                f"Раунд {session.current_round}/{session.total_rounds}. {waiting_text}",
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify waiting player: %s", e)


async def _run_next_round(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback to trigger the next round."""

    session_id: str = context.job.data["session_id"]
    sessions = _get_sessions(context)
    session = sessions.get(session_id)
    if not session:
        return
    await _start_round(context, session)


async def _bot_move(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback for the bot's answer and round summary."""

    session_id: str = context.job.data["session_id"]
    sessions = _get_sessions(context)
    session = sessions.get(session_id)
    if not session or not session.current_question:
        return

    session.jobs.pop("bot_move", None)

    accuracy = {"easy": 0.3, "medium": 0.6, "hard": 0.8}.get(
        session.difficulty, 0.3
    )
    bot_correct = random.random() < accuracy
    if bot_correct:
        session.bot_score += 1

    if session.current_question["type"] == "country_to_capital":
        country = session.current_question["country"]
        correct_display = f"{session.current_question['correct']} — {country}"
    else:
        correct_display = session.current_question["correct"]

    result_text = (
        f"Вопрос: {session.current_question['prompt']}\n"
        f"Игрок 1 → {session.answer_options.get(session.players[0], '-') } {'✅' if session.answers.get(session.players[0]) else '❌'}\n"
        f"Игрок 2 → {session.answer_options.get(session.players[1], '-') } {'✅' if session.answers.get(session.players[1]) else '❌'}\n"
        f"Бот-соперник → {'✅' if bot_correct else '❌'}\n"
        f"Правильный ответ: <b>{correct_display}</b>\n"
        f"Столица: {session.current_question['capital']}\n"
    )
    result_text += (
        f"Счёт: Команда {session.team_score} — Бот {session.bot_score} (Раунд {session.current_round}/{session.total_rounds})"
    )

    flag_path = get_flag_image_path(session.current_question["country"])
    for pid in session.players:
        chat_id = session.player_chats[pid]
        try:
            if flag_path:
                with flag_path.open("rb") as f:
                    await context.bot.send_photo(
                        chat_id,
                        f,
                        caption=result_text,
                        parse_mode="HTML",
                    )
            else:
                await context.bot.send_message(chat_id, result_text, parse_mode="HTML")
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send coop round result: %s", e)

    session.current_round += 1
    if session.current_round > session.total_rounds:
        await _finish_match(context, session.session_id)
        return

    delay = random.uniform(2, 3)
    job = context.application.job_queue.run_once(
        _run_next_round,
        delay,
        data={"session_id": session.session_id},
        name=f"coop_next_round_{session.session_id}",
    )
    session.jobs["next_round"] = job
    logger.debug("Next coop round in %.1f s", delay)


async def _finish_match(context: ContextTypes.DEFAULT_TYPE, session_id: str) -> None:
    sessions = _get_sessions(context)
    session = sessions.pop(session_id, None)
    if not session:
        return

    for job in session.jobs.values():
        job.schedule_removal()
    session.jobs.clear()

    if session.team_score > session.bot_score:
        result = "Команда победила!"
    elif session.team_score < session.bot_score:
        result = "Бот победил!"
    else:
        result = "Ничья!"

    text = f"Матч завершён. Счёт {session.team_score}:{session.bot_score}. {result}"
    for player_id in session.players:
        chat_id = session.player_chats[player_id]
        try:
            await context.bot.send_message(chat_id, text)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send coop final result: %s", e)


# ===== Command handlers =====


async def cmd_coop_capitals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a new cooperative match and provide a join code."""

    if update.effective_chat.type != "private":
        try:
            await update.message.reply_text(
                "Команду /coop_capitals можно использовать только в личке."
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify coop_capitals restriction: %s", e)
        return

    sessions = _get_sessions(context)
    _, existing = _find_user_session(sessions, update.effective_user.id)
    if existing:
        await update.message.reply_text("У вас уже есть активный матч. Используйте /coop_cancel для отмены.")
        return

    session_id = uuid.uuid4().hex[:8]
    session = CoopSession(session_id=session_id)
    session.players.append(update.effective_user.id)
    session.player_chats[update.effective_user.id] = update.effective_chat.id
    sessions[session_id] = session
    context.user_data["coop_pending"] = {"session_id": session_id, "stage": "name"}

    try:
        await update.message.reply_text("Матч создан. Как вас зовут?")
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to request player name: %s", e)


async def cmd_coop_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Join an existing cooperative match by session id."""

    if update.effective_chat.type != "private":
        try:
            await update.message.reply_text(
                "Команду /coop_join можно использовать только в личке."
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify coop_join restriction: %s", e)
        return

    if not context.args:
        await update.message.reply_text("Использование: /coop_join <код>")
        return

    session_id = context.args[0]
    sessions = _get_sessions(context)
    session = sessions.get(session_id)
    if not session:
        await update.message.reply_text("Матч не найден")
        return

    user_id = update.effective_user.id
    if user_id in session.players:
        await update.message.reply_text("Вы уже участвуете в этом матче")
        return
    if len(session.players) >= 2:
        await update.message.reply_text("В матче уже хватает игроков")
        return

    session.players.append(user_id)
    session.player_chats[user_id] = update.effective_chat.id
    context.user_data["coop_pending"] = {"session_id": session_id, "stage": "name"}

    try:
        await update.message.reply_text("Введите ваше имя")
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to request second player name: %s", e)


async def cmd_coop_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel an active cooperative match for a player."""

    sessions = _get_sessions(context)
    sid, session = _find_user_session(sessions, update.effective_user.id)
    if not session:
        await update.message.reply_text("Активных матчей не найдено")
        return

    sessions.pop(sid, None)
    for pid in session.players:
        chat_id = session.player_chats[pid]
        try:
            if pid == update.effective_user.id:
                await context.bot.send_message(chat_id, "Матч отменён")
            else:
                await context.bot.send_message(chat_id, "Соперник покинул матч. Игра отменена")
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify match cancel: %s", e)


async def cmd_coop_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only helper command to quickly start a match."""

    if update.effective_user.id != ADMIN_ID:
        return

    sessions = _get_sessions(context)
    session_id = uuid.uuid4().hex[:8]
    session = CoopSession(session_id=session_id)
    session.players = [update.effective_user.id, update.effective_user.id]
    session.player_chats = {
        update.effective_user.id: update.effective_chat.id,
    }
    session.total_rounds = 3
    session.difficulty = "medium"
    sessions[session_id] = session

    session.current_round = 1
    await _start_round(context, session)


async def msg_coop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle cooperative mode messages awaiting user input."""

    pending = context.user_data.get("coop_pending")
    if not pending:
        return

    session_id = pending.get("session_id")
    stage = pending.get("stage")
    sessions = _get_sessions(context)
    session = sessions.get(session_id)
    if not session:
        context.user_data.pop("coop_pending", None)
        return

    user_id = update.effective_user.id

    if stage == "name":
        if not update.message or not update.message.text:
            await update.message.reply_text("Пожалуйста, отправьте имя текстом")
            return
        session.player_names[user_id] = update.message.text.strip()
        if len(session.players) == 1:
            pending["stage"] = "invite"
            try:
                await update.message.reply_text(
                    "Имя сохранено. Пригласите второго игрока.",
                    reply_markup=coop_invite_kb(),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send invite keyboard: %s", e)
        else:
            context.user_data.pop("coop_pending", None)
            try:
                await update.message.reply_text(
                    "Имя сохранено. Выберите число раундов.",
                    reply_markup=coop_rounds_kb(session_id, user_id),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning(
                    "Failed to send rounds keyboard to second player: %s", e
                )
            first_player = session.players[0]
            first_chat = session.player_chats[first_player]
            try:
                await context.bot.send_message(
                    first_chat,
                    "Второй игрок присоединился. Выберите число раундов.",
                    reply_markup=coop_rounds_kb(session_id, first_player),
                )
                context.application.user_data.get(first_player, {}).pop(
                    "coop_pending", None
                )
            except (TelegramError, HTTPError) as e:
                logger.warning(
                    "Failed to send rounds keyboard to first player: %s", e
                )
        return

    if stage == "invite":
        link = f"https://t.me/{context.bot.username}?start=coop_{session_id}"
        if update.message and update.message.contact:
            contact = update.message.contact
            if contact.user_id:
                try:
                    await context.bot.send_message(
                        contact.user_id,
                        f"{session.player_names.get(user_id, 'Игрок')} приглашает вас сыграть в дуэт против бота.\n{link}",
                    )
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to send invite to contact: %s", e)
            try:
                await update.message.reply_text(
                    "Приглашение отправлено",
                    reply_markup=ReplyKeyboardRemove(),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to confirm invite: %s", e)
        else:
            try:
                await update.message.reply_text(
                    f"Поделитесь ссылкой: {link}",
                    reply_markup=ReplyKeyboardRemove(),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send invite link: %s", e)
        context.user_data.pop("coop_pending", None)


# ===== Callback handler =====


async def cb_coop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query

    parts = q.data.split(":")
    action = parts[1]

    sessions = _get_sessions(context)

    if action == "rounds":
        session_id = parts[2]
        player_id = int(parts[3])
        rounds = int(parts[4])
        session = sessions.get(session_id)
        if not session:
            await q.answer()
            return
        if update.effective_user.id not in session.players:
            await q.answer("Не вы участвуете", show_alert=True)
            return
        if player_id != update.effective_user.id:
            await q.answer("Не ваша кнопка", show_alert=True)
            return
        if session.total_rounds:
            await q.answer("Число раундов уже выбрано", show_alert=True)
            try:
                await q.edit_message_reply_markup(None)
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to clear rounds keyboard: %s", e)
            return
        session.total_rounds = rounds
        await q.answer()
        try:
            await q.edit_message_reply_markup(None)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to clear rounds keyboard: %s", e)
        for pid in session.players:
            chat_id = session.player_chats[pid]
            try:
                await context.bot.send_message(
                    chat_id,
                    "Выберите сложность соперника.",
                    reply_markup=coop_difficulty_kb(session_id, pid),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send difficulty keyboard: %s", e)
        return

    if action == "diff":
        session_id = parts[2]
        player_id = int(parts[3])
        difficulty = parts[4]
        session = sessions.get(session_id)
        if not session:
            await q.answer()
            return
        if update.effective_user.id not in session.players:
            await q.answer("Не вы участвуете", show_alert=True)
            return
        if player_id != update.effective_user.id:
            await q.answer("Не ваша кнопка", show_alert=True)
            return
        if session.difficulty:
            await q.answer("Сложность уже выбрана", show_alert=True)
            try:
                await q.edit_message_reply_markup(None)
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to clear difficulty keyboard: %s", e)
            return
        session.difficulty = difficulty
        await q.answer()
        try:
            await q.edit_message_reply_markup(None)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to clear difficulty keyboard: %s", e)
        if session.total_rounds and session.difficulty:
            session.current_round = 1
            await _start_round(context, session)
        return

    if action != "ans":
        await q.answer()
        return

    session_id = parts[2]
    player_id = int(parts[3])
    idx = int(parts[4])
    session = sessions.get(session_id)
    if not session or not session.current_question:
        await q.answer()
        return
    if player_id != update.effective_user.id:
        await q.answer("Не ваша кнопка", show_alert=True)
        return
    if player_id != session.players[session.current_turn_index]:
        await q.answer("Сейчас не ваш ход", show_alert=True)
        return
    if player_id in session.answers:
        await q.answer("Вы уже ответили", show_alert=True)
        return

    option = session.current_question["options"][idx]
    correct = option == session.current_question["correct"]
    session.answers[player_id] = correct
    session.answer_options[player_id] = option
    if correct:
        session.team_score += 1

    await q.answer()
    try:
        await q.edit_message_reply_markup(None)
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to clear coop buttons: %s", e)

    session.current_turn_index += 1
    if session.current_turn_index < len(session.players):
        next_pid = session.players[session.current_turn_index]
        next_chat = session.player_chats[next_pid]
        try:
            msg = await context.bot.send_message(
                next_chat,
                f"Раунд {session.current_round}/{session.total_rounds}\n{session.current_question['prompt']}",
                reply_markup=coop_answer_kb(
                    session.session_id, next_pid, session.current_question["options"]
                ),
                parse_mode="HTML",
            )
            session.question_message_ids[next_pid] = msg.message_id
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send coop question: %s", e)

        for pid in session.players:
            if pid == next_pid:
                continue
            chat_id = session.player_chats[pid]
            try:
                await context.bot.send_message(chat_id, "Ожидаем ход другого игрока.")
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to notify waiting player: %s", e)
        return

    for pid in session.players:
        chat_id = session.player_chats[pid]
        try:
            await context.bot.send_message(chat_id, "Бот думает…")
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify bot thinking: %s", e)

    job = context.application.job_queue.run_once(
        _bot_move,
        session.bot_think_delay,
        data={"session_id": session.session_id},
        name=f"coop_bot_move_{session.session_id}",
    )
    session.jobs["bot_move"] = job

