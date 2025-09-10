from telegram import Update
from telegram.ext import ContextTypes

from app import DATA

async def cb_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Карточки: здесь будет выбор континента/режима и показ карточек.")
