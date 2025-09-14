"""Handlers for the main menu flow."""

import random

from telegram import Update
from telegram.ext import ContextTypes

from app import DATA
from .state import CardSession
from .keyboards import (
    main_menu_kb,
    continent_kb,
    sprint_start_kb,
    list_result_kb,
    back_to_menu_kb,
    test_start_kb,
)
from .flags import get_country_flag

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
    await context.bot.send_message(chat_id, WELCOME, reply_markup=main_menu_kb())

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

    elif data.startswith("menu:cards:"):
        parts = data.split(":", 2)
        continent = parts[2]
        context.user_data["continent"] = continent
        continent_filter = None if continent == "Весь мир" else continent
        countries = DATA.countries(continent_filter)
        queue = [
            (c, random.choice(["country_to_capital", "capital_to_country"]))
            for c in countries
        ]
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

    elif data.startswith("menu:list:"):
        parts = data.split(":", 2)
        continent = parts[2]
        continent_filter = None if continent == "Весь мир" else continent
        countries = DATA.countries(continent_filter)
        lines = []
        for country in countries:
            capital = DATA.capital_by_country.get(country, "")
            flag = get_country_flag(country)
            lines.append(f"{flag} {country} - Столица: {capital}")

        # Telegram messages are limited to 4096 characters. Chunk the list
        # so that selecting "Весь мир" does not exceed that limit.
        title = f"{continent}:\n"
        chunks = []
        current = title
        for line in lines:
            line_text = f"{line}\n"
            if len(current) + len(line_text) > 4000:
                chunks.append(current.rstrip())
                current = line_text
            else:
                current += line_text
        chunks.append(current.rstrip())

        chat_id = update.effective_chat.id
        if len(chunks) == 1:
            await q.edit_message_text(chunks[0], reply_markup=list_result_kb())
        else:
            await q.edit_message_text(chunks[0])
            for chunk in chunks[1:-1]:
                await context.bot.send_message(chat_id, chunk)
            await context.bot.send_message(chat_id, chunks[-1], reply_markup=list_result_kb())

    elif data == "menu:coop":
        from telegram import Update
        from .handlers_coop import cmd_coop_capitals

        fake_update = Update(update.update_id, message=q.message)
        await cmd_coop_capitals(fake_update, context)
        try:
            await q.message.delete()
        except Exception:
            pass

    elif data == "menu:main":
        await q.edit_message_text(WELCOME, reply_markup=main_menu_kb())
