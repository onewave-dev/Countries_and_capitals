from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu_kb():
    rows = [
        [InlineKeyboardButton("📘 Флэш-карточки", callback_data="menu:cards")],
        [InlineKeyboardButton("⏱ Игра на время", callback_data="menu:sprint")],
        [InlineKeyboardButton("🤝 Дуэт против Бота", callback_data="menu:coop")],
    ]
    return InlineKeyboardMarkup(rows)
