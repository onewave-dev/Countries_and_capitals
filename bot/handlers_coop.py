"""Handlers for the cooperative two-vs-bot mode."""

from __future__ import annotations

import os
import random
import uuid
from typing import Dict

from telegram import Update
from telegram.ext import ContextTypes

from app import DATA
from .state import CoopSession
from .questions import pick_question
from .keyboards import (
    coop_join_kb,
    coop_rounds_kb,
    coop_difficulty_kb,
    coop_answer_kb,
)


ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))


# ===== Helpers =====


def _get_sessions(chat_data: Dict) -> Dict[str, CoopSession]:
    """Return the session mapping for a chat, creating if missing."""

    return chat_data.setdefault("sessions", {})


async def _start_round(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, session_id: str
) -> None:
    """Generate question and prompt the first player."""

    chat_sessions = context.application.chat_data[chat_id]["sessions"]
    session: CoopSession = chat_sessions[session_id]

    question = pick_question(DATA, session.continent_filter, session.mode)
    session.current_question = question
    session.turn = 0

    await context.bot.send_message(
        chat_id,
        f"Раунд {session.current_round}/{session.total_rounds}\nИгрок 1: {question['prompt']}",
        reply_markup=coop_answer_kb(
            session.session_id, session.players[0], question["options"]
        ),
    )


async def _next_round(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    chat_id = data["chat_id"]
    session_id = data["session_id"]
    chat_sessions = context.application.chat_data.get(chat_id, {}).get("sessions", {})
    session: CoopSession | None = chat_sessions.get(session_id)
    if not session:
        return

    session.current_round += 1
    if session.current_round > session.total_rounds:
        await _finish_match(context, chat_id, session_id)
        return

    await _start_round(context, chat_id, session_id)


async def _finish_match(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, session_id: str
) -> None:
    chat_sessions = context.application.chat_data.get(chat_id, {}).get("sessions", {})
    session: CoopSession | None = chat_sessions.pop(session_id, None)
    if not session:
        return

    if session.team_score > session.bot_score:
        result = "Команда победила!"
    elif session.team_score < session.bot_score:
        result = "Бот победил!"
    else:
        result = "Ничья!"

    await context.bot.send_message(
        chat_id,
        f"Матч завершён. Счёт {session.team_score}:{session.bot_score}. {result}",
    )


# ===== Command handlers =====


async def cmd_coop_capitals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point to start a cooperative match in group chats."""

    if update.effective_chat.type not in {"group", "supergroup"}:
        await update.message.reply_text(
            "Команду /coop_capitals можно использовать только в группе."
        )
        return

    session_id = uuid.uuid4().hex
    session = CoopSession(session_id=session_id, chat_id=update.effective_chat.id)

    sessions = _get_sessions(context.chat_data)
    sessions[session_id] = session

    await update.message.reply_text(
        "Дуэт против Бота: нажмите, чтобы присоединиться.",
        reply_markup=coop_join_kb(session_id),
    )


async def cmd_coop_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only helper command to quickly start a match with two slots filled."""

    if update.effective_user.id != ADMIN_ID:
        return

    session_id = uuid.uuid4().hex
    session = CoopSession(
        session_id=session_id,
        chat_id=update.effective_chat.id,
        players=[update.effective_user.id, update.effective_user.id],
        total_rounds=3,
        difficulty="medium",
    )
    sessions = _get_sessions(context.chat_data)
    sessions[session_id] = session
    session.current_round = 1
    await _start_round(context, update.effective_chat.id, session_id)


# ===== Callback handler =====


async def cb_coop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    parts = q.data.split(":")
    action = parts[1]

    sessions = _get_sessions(context.chat_data)

    if action == "join":
        session_id = parts[2]
        session = sessions.get(session_id)
        if not session:
            await q.edit_message_text("Матч не найден")
            return
        user_id = update.effective_user.id
        if user_id in session.players:
            await q.answer("Вы уже участвуете")
            return
        if len(session.players) >= 2:
            await q.answer("Уже хватает игроков")
            return
        session.players.append(user_id)
        if len(session.players) == 2:
            await q.edit_message_text(
                "Игроки зарегистрированы. Выберите число раундов:",
                reply_markup=coop_rounds_kb(session_id),
            )
        else:
            await q.edit_message_text(
                "Первый игрок зарегистрирован. Ждём второго…",
                reply_markup=coop_join_kb(session_id),
            )
        return

    if action == "rounds":
        session_id = parts[2]
        rounds = int(parts[3])
        session = sessions.get(session_id)
        if not session:
            await q.edit_message_text("Матч не найден")
            return
        session.total_rounds = rounds
        await q.edit_message_text(
            "Сложность бота:", reply_markup=coop_difficulty_kb(session_id)
        )
        return

    if action == "diff":
        session_id = parts[2]
        diff = parts[3]
        session = sessions.get(session_id)
        if not session:
            await q.edit_message_text("Матч не найден")
            return
        session.difficulty = diff
        session.current_round = 1
        await q.edit_message_text("Матч начинается!")
        await _start_round(context, session.chat_id, session_id)
        return

    if action == "ans":
        session_id = parts[2]
        player_id = int(parts[3])
        idx = int(parts[4])
        session = sessions.get(session_id)
        if not session or not hasattr(session, "current_question"):
            await q.edit_message_text("Матч не найден")
            return
        if player_id != update.effective_user.id:
            await q.answer("Не ваша очередь", show_alert=True)
            return
        if session.turn not in {0, 1}:
            await q.answer()
            return

        option = session.current_question["options"][idx]
        correct = option == session.current_question["correct"]
        if correct:
            session.team_score += 1

        if session.turn == 0:
            session.turn = 1
            await q.edit_message_text(
                f"Игрок 1: {option} {'✅' if correct else '❌'}\nИгрок 2: {session.current_question['prompt']}",
                reply_markup=coop_answer_kb(
                    session.session_id,
                    session.players[1],
                    session.current_question["options"],
                ),
            )
            return

        # second player's answer
        session.turn = 2
        await q.edit_message_text(
            f"Игрок 2: {option} {'✅' if correct else '❌'}",
        )

        # Bot move
        accuracy = {"easy": 0.3, "medium": 0.6, "hard": 0.8}.get(
            session.difficulty, 0.3
        )
        bot_correct = random.random() < accuracy
        if bot_correct:
            session.bot_score += 1

        await context.bot.send_message(
            session.chat_id,
            (
                f"Бот {'угадал' if bot_correct else 'ошибся'} — правильный ответ: "
                f"{session.current_question['correct']}\n"
                f"Счёт: Команда {session.team_score} — Бот {session.bot_score} "
                f"(Раунд {session.current_round}/{session.total_rounds})"
            ),
        )

        # Schedule next round or finish
        context.application.job_queue.run_once(
            _next_round,
            2,
            data={"chat_id": session.chat_id, "session_id": session.session_id},
        )
        return

