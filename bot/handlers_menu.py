"""Handlers for the main menu flow."""

import os

from telegram import Update
from telegram.ext import ContextTypes

from app import DATA
from .keyboards import (
    main_menu_kb,
    continent_kb,
    sprint_start_kb,
    list_result_kb,
    back_to_menu_kb,
    test_start_kb,
    cards_mode_kb,
)
from .flags import get_country_flag

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

WELCOME = (
    "Привет! Это бот для тренировки знаний столицы ↔ страна.\n"
    "Выбери режим:"
)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith("coop_"):
        from .handlers_coop import cmd_coop_join

        session_id = context.args[0][5:]
        context.args = [session_id]
        await cmd_coop_join(update, context)
        return

    chat_id = update.effective_chat.id
    is_admin = update.effective_user.id == ADMIN_ID
    await context.bot.send_message(
        chat_id, WELCOME, reply_markup=main_menu_kb(is_admin)
    )

def build_country_list_chunks(countries: list[str], title: str) -> list[str]:
    """Return Telegram-ready chunks listing ``countries`` with capitals."""

    lines: list[str] = []
    for country in countries:
        capital = DATA.capital_by_country.get(country, "")
        flag = get_country_flag(country)
        lines.append(f"{flag} {country} - Столица: {capital}")

    chunks: list[str] = []
    current = title
    for line in lines:
        line_text = f"{line}\n"
        if len(current) + len(line_text) > 4000:
            chunks.append(current.rstrip())
            current = line_text
        else:
            current += line_text
    chunks.append(current.rstrip())
    return chunks


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all ``^menu:`` callbacks."""

    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "menu:void":
        return

    if data in {"menu:cards", "menu:sprint", "menu:list"}:
        mode = data.split(":")[1]
        if mode == "cards":
            text = "📘 Флэш-карточки: выбери континент."
        elif mode == "sprint":
            text = "⏱ Игра на время: выбери континент."
        else:
            text = "📋 Учить по спискам: выбери континент."
        await q.edit_message_text(
            text,
            reply_markup=continent_kb(
                f"menu:{mode}", include_menu=(mode == "list")
            ),
        )
    elif data == "menu:test":
        await q.edit_message_text(
            "📝 Тест: выбери режим.", reply_markup=test_start_kb()
        )
    elif data == "menu:coop":
        from .handlers_coop import cmd_coop_capitals

        await q.edit_message_text("🤝 Дуэт против Бота")
        await cmd_coop_capitals(update, context)
    elif data == "menu:coop_admin":
        context.user_data["coop_admin"] = True
        await q.edit_message_text(
            "🤝 Дуэт против Бота: выбери континент.",
            reply_markup=continent_kb("coop"),
        )

    elif data.startswith("menu:cards:"):
        parts = data.split(":", 2)
        continent = parts[2]
        context.user_data["continent"] = continent
        continent_filter = None if continent == "Весь мир" else continent
        countries = sorted(DATA.countries(continent_filter))
        context.user_data.pop("card_session", None)
        context.user_data["card_setup"] = {
            "continent": continent,
            "continent_filter": continent_filter,
            "countries": countries,
            "mode": None,
            "subcategory": None,
            "letter": None,
        }
        context.user_data.pop("card_subset", None)
        context.user_data.pop("card_letter_pending", None)
        text = (
            f"📘 Флэш-карточки — {continent}.\n"
            "Выбери, как будем учить столицы."
        )
        await q.edit_message_text(text, reply_markup=cards_mode_kb())

    elif data.startswith("menu:sprint:"):
        parts = data.split(":", 2)
        continent = parts[2]
        context.user_data["continent"] = continent
        await q.edit_message_text(
            "У тебя будет 60 секунд, чтобы ответить как можно больше вопросов правильно.",
            reply_markup=sprint_start_kb(continent),
        )

    elif data.startswith("menu:list:"):
        parts = data.split(":", 2)
        continent = parts[2]
        continent_filter = None if continent == "Весь мир" else continent
        countries = DATA.countries(continent_filter)
        title = f"{continent}:\n"
        chunks = build_country_list_chunks(countries, title)

        chat_id = update.effective_chat.id
        if len(chunks) == 1:
            await q.edit_message_text(chunks[0], reply_markup=list_result_kb())
        else:
            await q.edit_message_text(chunks[0])
            for chunk in chunks[1:-1]:
                await context.bot.send_message(chat_id, chunk)
            await context.bot.send_message(chat_id, chunks[-1], reply_markup=list_result_kb())

    elif data == "menu:main":
        is_admin = update.effective_user.id == ADMIN_ID
        await q.edit_message_text(WELCOME, reply_markup=main_menu_kb(is_admin))
