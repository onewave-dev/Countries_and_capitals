from telegram import Update
from telegram.ext import ContextTypes

async def cb_coop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Кооператив: запускается в группе командой /coop_capitals.")
