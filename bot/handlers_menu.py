"""Handlers for the main menu flow."""

import random

from telegram import Update
from telegram.ext import ContextTypes

from app import DATA
from .state import CardSession
from .keyboards import main_menu_kb, continent_kb, sprint_start_kb

WELCOME = (
    "Привет! Это бот для тренировки знаний столицы ↔ страна.\n"
    "Выбери режим:"
)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id, WELCOME, reply_markup=main_menu_kb())

async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all ``^menu:`` callbacks."""

    q = update.callback_query
    await q.answer()
    data = q.data

    if data in {"menu:cards", "menu:sprint"}:
        mode = data.split(":")[1]
        text = "📘 Флэш-карточки: выбери континент." if mode == "cards" else "⏱ Игра на время: выбери континент."
        await q.edit_message_text(text, reply_markup=continent_kb(f"menu:{mode}"))

    elif data.startswith("menu:cards:"):
        parts = data.split(":", 2)
        continent = parts[2]
        context.user_data["continent"] = continent
        continent_filter = None if continent == "Весь мир" else continent
        queue = DATA.items(continent_filter, "mixed")
        random.shuffle(queue)
        session = CardSession(
            user_id=update.effective_user.id,
            continent_filter=continent_filter,
            mode="mixed",
            queue=queue,
        )
        context.user_data["card_session"] = session
        from .handlers_cards import _next_card  # local import to avoid circular

        await _next_card(update, context)

    elif data.startswith("menu:sprint:"):
        parts = data.split(":", 2)
        continent = parts[2]
        context.user_data["continent"] = continent
        await q.edit_message_text(
            "У тебя будет 60 секунд, чтобы ответить как можно больше вопросов правильно.",
            reply_markup=sprint_start_kb(continent),
        )

    elif data == "menu:coop":
        await q.edit_message_text(
            "🤝 Дуэт против Бота: запускай в групповом чате командой /coop_capitals",
            reply_markup=None,
        )
