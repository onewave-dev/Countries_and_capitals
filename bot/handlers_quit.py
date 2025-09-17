"""Handlers to terminate any active sessions."""

from collections.abc import MutableMapping

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from httpx import HTTPError

from .handlers_coop import (
    _get_sessions,
    _find_user_session_global,
    _remove_session,
)


SESSION_ENDED = "Сессия завершена. Нажмите /start, чтобы начать заново."
SESSION_STATE_KEYS = {
    "card_session",
    "sprint_session",
    "test_session",
    "coop_pending",
    "sprint_allow_skip",
    "coop_admin",
    "continent",
}


def _clear_user_state(user_data: MutableMapping[str, object] | None) -> None:
    """Remove all session-related data from ``user_data`` if available."""

    if not isinstance(user_data, MutableMapping):
        return

    job = user_data.pop("sprint_job", None)
    if job:
        try:
            job.schedule_removal()
        except AttributeError:
            pass

    for key in SESSION_STATE_KEYS:
        user_data.pop(key, None)


async def cmd_quit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel all running sessions for the caller and notify participants."""

    _clear_user_state(context.user_data)

    _get_sessions(context)
    _, session = _find_user_session_global(context, update.effective_user.id)
    if session:
        _remove_session(context, session)
        application = getattr(context, "application", None)
        app_user_data = getattr(application, "user_data", {}) if application else {}
        for pid in session.players:
            _clear_user_state(app_user_data.get(pid))
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

