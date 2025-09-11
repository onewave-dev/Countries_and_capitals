"""Handlers for the main menu flow."""

from telegram import Update
from telegram.ext import ContextTypes

from .keyboards import main_menu_kb, continent_kb, direction_kb

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

    elif data.startswith("menu:cards:") or data.startswith("menu:sprint:"):
        parts = data.split(":", 2)
        mode = parts[1]
        continent = parts[2]
        context.user_data["continent"] = continent
        await q.edit_message_text(
            "Выбери направление вопросов:",
            reply_markup=direction_kb(mode, continent),
        )

    elif data == "menu:coop":
        await q.edit_message_text(
            "🤝 Дуэт против Бота: запускай в групповом чате командой /coop_capitals",
            reply_markup=None,
        )
