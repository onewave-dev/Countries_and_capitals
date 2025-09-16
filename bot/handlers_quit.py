"""Handlers to terminate any active sessions."""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from httpx import HTTPError

from .handlers_coop import (
    _get_sessions,
    _find_user_session_global,
    _remove_session,
)


SESSION_ENDED = "Сессия прекращена. Для запуска прогаммы используйте /start"


async def cmd_quit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel all running sessions for the caller and notify participants."""

    user_data = context.user_data
    job = user_data.pop("sprint_job", None)
    if job:
        job.schedule_removal()

    for key in [
        "card_session",
        "sprint_session",
        "test_session",
        "coop_pending",
        "sprint_allow_skip",
    ]:
        user_data.pop(key, None)

    _get_sessions(context)
    _, session = _find_user_session_global(context, update.effective_user.id)
    if session:
        _remove_session(context, session)
        for pid in session.players:
            chat_id = session.player_chats.get(pid, pid)
            try:
                await context.bot.send_message(chat_id, SESSION_ENDED)
            except (TelegramError, HTTPError):
                pass
        return

    chat_id = update.effective_chat.id
    try:
        await context.bot.send_message(chat_id, SESSION_ENDED)
    except (TelegramError, HTTPError):
        pass


__all__ = ("cmd_quit",)

