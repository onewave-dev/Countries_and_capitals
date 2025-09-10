from telegram import Update
from telegram.ext import ContextTypes
from .keyboards import main_menu_kb

WELCOME = (
    "Привет! Это бот для тренировки знаний столицы ↔ страна.\n"
    "Выбери режим:"
)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id, WELCOME, reply_markup=main_menu_kb())

async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "menu:cards":
        # открыть подменю карточек
        await q.edit_message_text(
            "📘 Флэш-карточки: выбери континент и тип вопросов.",
            reply_markup=None
        )
        # маршрут к cards:
        await context.bot.send_message(q.message.chat_id, "Старт карточек (заглушка).")
        # Реально: отправить инлайн-кнопки выбора параметров и вызвать cards flow

    elif data == "menu:sprint":
        await q.edit_message_text(
            "⏱ Игра на время: длительность 60 сек. Вопросы в обе стороны.",
            reply_markup=None
        )
        await context.bot.send_message(q.message.chat_id, "Старт спринта (заглушка).")

    elif data == "menu:coop":
        await q.edit_message_text(
            "🤝 Дуэт против Бота: запускай в групповом чате командой /coop_capitals",
            reply_markup=None
        )
