from telegram import Update
from telegram.ext import ContextTypes

async def cb_sprint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Спринт: здесь будет 60-секундная серия вопросов с кнопками.")
