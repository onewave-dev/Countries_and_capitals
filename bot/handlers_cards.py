"""Handlers for the flash-cards training mode."""

import logging
import random
import asyncio
from collections.abc import Iterable

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from httpx import HTTPError

from app import DATA
from .state import CardSession, add_to_repeat, get_user_stats
from .questions import make_card_question
from .keyboards import (
    cards_kb,
    cards_repeat_kb,
    cards_finish_kb,
    main_menu_kb,
    fact_more_kb,
    cards_mode_kb,
    cards_subcategories_kb,
    cards_preview_kb,
    continent_kb,
)
from .flags import get_country_flag, get_flag_image_path
from .handlers_menu import WELCOME, ADMIN_ID, build_country_list_chunks
from .facts import get_static_fact, generate_llm_fact


logger = logging.getLogger(__name__)


def select_matching_countries(countries: Iterable[str]) -> set[str]:
    """Return countries whose capital matches the country name."""

    result: set[str] = set()
    for country in countries:
        capital = DATA.capital_by_country.get(country, "")
        if capital and capital.casefold() == country.casefold():
            result.add(country)
    return result


def select_countries_by_letter(countries: Iterable[str], letter: str) -> set[str]:
    """Return countries whose capital starts with the provided ``letter``.

    ``letter`` must consist of a single alphabetic character. Any other input
    yields an empty result.
    """

    normalized = letter.strip()
    if len(normalized) != 1 or not normalized.isalpha():
        return set()

    normalized = normalized.casefold()
    result: set[str] = set()
    for country in countries:
        capital = DATA.capital_by_country.get(country, "").lstrip()
        if not capital:
            continue
        first_char = capital[0].casefold()
        if first_char == normalized:
            result.add(country)
    return result


def select_remaining_countries(
    countries: Iterable[str], *exclude_groups: Iterable[str]
) -> set[str]:
    """Return countries that are not present in ``exclude_groups``."""

    excluded: set[str] = set()
    for group in exclude_groups:
        excluded.update(group)
    return set(countries) - excluded


async def _cleanup_preview_messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    keep_message_id: int | None,
) -> None:
    """Delete previously sent preview chunks leaving ``keep_message_id`` intact."""

    message_ids: list[int] = context.user_data.pop("card_preview_messages", [])
    context.user_data.pop("card_preview_chunks", None)
    chat_id = update.effective_chat.id
    for message_id in message_ids:
        if keep_message_id is not None and message_id == keep_message_id:
            continue
        try:
            await context.bot.delete_message(chat_id, message_id)
        except (TelegramError, HTTPError) as exc:
            logger.debug("Failed to delete preview message %s: %s", message_id, exc)


async def _show_preview(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    subset: Iterable[str],
    title: str,
    back_action: str,
    origin_message_id: int | None = None,
) -> bool:
    """Display preview list of countries before starting the session."""

    countries = sorted(set(subset))
    if not countries:
        return False

    context.user_data["card_subset"] = countries
    chunks = build_country_list_chunks(countries, title)
    context.user_data["card_preview_chunks"] = chunks
    chat_id = update.effective_chat.id
    message_id = origin_message_id
    if message_id is None and update.callback_query:
        message_id = update.callback_query.message.message_id
    elif message_id is None and update.effective_message:
        message_id = update.effective_message.message_id

    preview_messages: list[int] = []

    try:
        if len(chunks) == 1:
            if message_id is not None:
                msg = await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=chunks[0],
                    reply_markup=cards_preview_kb(back_action),
                )
                preview_messages.append(msg.message_id)
            else:
                msg = await context.bot.send_message(
                    chat_id,
                    chunks[0],
                    reply_markup=cards_preview_kb(back_action),
                )
                preview_messages.append(msg.message_id)
        else:
            if message_id is not None:
                msg = await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=chunks[0],
                )
                preview_messages.append(msg.message_id)
            else:
                msg = await context.bot.send_message(chat_id, chunks[0])
                preview_messages.append(msg.message_id)
            for chunk in chunks[1:-1]:
                sent = await context.bot.send_message(chat_id, chunk)
                preview_messages.append(sent.message_id)
            last = await context.bot.send_message(
                chat_id, chunks[-1], reply_markup=cards_preview_kb(back_action)
            )
            preview_messages.append(last.message_id)
    except (TelegramError, HTTPError) as exc:
        logger.warning("Failed to display preview list: %s", exc)
        return False

    context.user_data["card_preview_messages"] = preview_messages
    context.user_data.pop("card_letter_pending", None)
    return True


async def _next_card(
    update: Update, context: ContextTypes.DEFAULT_TYPE, replace_message: bool = True
) -> None:
    """Send the next card or finish the session if queue is empty.

    Parameters
    ----------
    update: Update
        The incoming update triggering the next card.
    context: ContextTypes.DEFAULT_TYPE
        The context provided by the handler.
    replace_message: bool, optional
        When ``True`` (default), the previous message with options is edited with
        the next question. When ``False``, the next question is sent as a new
        message instead of editing the existing one. This is used after sending
        feedback on a user's answer so that the feedback message is preserved.
        The final card in the queue is always sent as a new message.
    """

    session: CardSession = context.user_data["card_session"]
    if not session.queue:
        await _finish_session(update, context)
        return

    is_last = len(session.queue) == 1
    raw = session.queue.pop(0)
    if isinstance(raw, tuple):
        country, direction = raw
        item = (
            country
            if direction == "country_to_capital"
            else DATA.capital_by_country[country]
        )
    else:
        item = raw
        if raw in DATA.capital_by_country:
            direction = "country_to_capital"
        else:
            direction = "capital_to_country"
    question = make_card_question(
        DATA, item, direction, session.continent_filter
    )
    session.current = question  # dynamic attribute to store current card
    session.stats["shown"] += 1
    session.current_answered = False

    logger.debug(
        "Generated card question for user %s: %s -> %s",
        session.user_id,
        question["prompt"],
        question["answer"],
    )

    if update.callback_query and replace_message and not is_last:
        q = update.callback_query
        try:
            await q.edit_message_text(
                question["prompt"],
                reply_markup=cards_kb(question["options"]),
                parse_mode="HTML",
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send card: %s", e)
            return
    else:
        chat_id = update.effective_chat.id
        try:
            await context.bot.send_message(
                chat_id,
                question["prompt"],
                reply_markup=cards_kb(question["options"]),
                parse_mode="HTML",
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send card: %s", e)
            return


async def _finish_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Output final stats and unknown items."""

    session: CardSession | None = context.user_data.get("card_session")
    if not session:
        return

    context.user_data.pop("card_setup", None)
    context.user_data.pop("card_subset", None)
    context.user_data.pop("card_letter_pending", None)
    context.user_data.pop("card_preview_messages", None)
    context.user_data.pop("card_preview_chunks", None)

    logger.debug(
        "Card session finished for user %s: stats=%s unknown=%d",
        session.user_id,
        session.stats,
        len(session.unknown_set),
    )

    text = (
        f"Сессия завершена. Показано: {session.stats['shown']}, "
        f"знаю: {session.stats['known']}."
    )
    reply_markup = cards_finish_kb()
    if session.stats["known"] < session.stats["shown"]:
        if hasattr(session, "current") and not session.current_answered:
            item = (
                session.current["country"]
                if session.current["type"] == "country_to_capital"
                else session.current["capital"]
            )
            if item not in session.unknown_set:
                session.unknown_set.add(item)
                add_to_repeat(context.user_data, {item})
        unknown_lines = []
        for item in sorted(session.unknown_set):
            if item in DATA.capital_by_country:
                country = item
                capital = DATA.capital_by_country[item]
            else:
                country = DATA.country_by_capital[item]
                capital = item
            flag = get_country_flag(country)
            pair = f"{flag} {country} — Столица: {capital}"
            unknown_lines.append(pair)
        text += "\nНеизвестные:\n" + "\n".join(unknown_lines)
        reply_markup = cards_repeat_kb()
    else:
        context.user_data.pop("card_session", None)

    chat_id = update.effective_chat.id
    try:
        await context.bot.send_message(chat_id, text, reply_markup=reply_markup)
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to send session results: %s", e)
        return


async def cb_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all ``^cards:`` callbacks."""

    q = update.callback_query

    parts = q.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if parts == ["cards", "void"]:
        await q.answer()
        return

    if action == "menu":
        await q.answer()
        await _cleanup_preview_messages(update, context, q.message.message_id)
        context.user_data.pop("card_session", None)
        context.user_data.pop("card_setup", None)
        context.user_data.pop("card_subset", None)
        context.user_data.pop("card_letter_pending", None)
        context.user_data.pop("card_prompt_message_id", None)
        try:
            await q.edit_message_text(
                WELCOME,
                reply_markup=main_menu_kb(update.effective_user.id == ADMIN_ID),
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to return to menu: %s", e)
        return

    setup: dict | None = context.user_data.get("card_setup")

    if action == "back":
        await q.answer()
        target = parts[2] if len(parts) > 2 else ""
        await _cleanup_preview_messages(update, context, q.message.message_id)
        if target == "continent":
            context.user_data.pop("card_session", None)
            context.user_data.pop("card_setup", None)
            context.user_data.pop("card_subset", None)
            context.user_data.pop("card_letter_pending", None)
            context.user_data.pop("card_prompt_message_id", None)
            text = "📘 Флэш-карточки: выбери континент."
            try:
                await q.edit_message_text(
                    text, reply_markup=continent_kb("menu:cards")
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to show continent selection: %s", exc)
            return
        if not setup:
            try:
                await q.edit_message_text(
                    "Выбор континента не найден. Нажмите /start, чтобы начать заново.",
                    reply_markup=main_menu_kb(update.effective_user.id == ADMIN_ID),
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to handle missing setup: %s", exc)
            return
        context.user_data.pop("card_subset", None)
        context.user_data.pop("card_letter_pending", None)
        context.user_data.pop("card_prompt_message_id", None)
        if target == "mode":
            text = (
                f"📘 Флэш-карточки — {setup['continent']}.\n"
                "Выбери, как будем учить столицы."
            )
            try:
                await q.edit_message_text(text, reply_markup=cards_mode_kb())
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to show mode selection: %s", exc)
            return
        if target == "subcategory":
            text = (
                f"📘 Флэш-карточки — {setup['continent']}.\n"
                "Выбери подкатегорию."
            )
            try:
                await q.edit_message_text(
                    text, reply_markup=cards_subcategories_kb()
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to show subcategory selection: %s", exc)
            return
        return

    if action == "mode":
        await q.answer()
        if not setup:
            try:
                await q.edit_message_text(
                    "Выбор континента не найден. Нажмите /start, чтобы начать заново.",
                    reply_markup=main_menu_kb(update.effective_user.id == ADMIN_ID),
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to handle missing setup: %s", exc)
            return
        option = parts[2] if len(parts) > 2 else ""
        if option == "all":
            setup["mode"] = "all"
            setup["subcategory"] = None
            setup["letter"] = None
            await _cleanup_preview_messages(update, context, q.message.message_id)
            context.user_data.pop("card_prompt_message_id", None)
            subset = setup["countries"]
            title = (
                f"{setup['continent']} — все страны ({len(subset)}):\n"
            )
            if not await _show_preview(
                update, context, subset, title, "cards:back:mode"
            ):
                try:
                    await q.edit_message_text(
                        "Не удалось подготовить список. Попробуйте выбрать другую опцию.",
                        reply_markup=cards_mode_kb(),
                    )
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to notify preview error: %s", exc)
            return
        if option == "subsets":
            setup["mode"] = "subsets"
            setup["subcategory"] = None
            setup["letter"] = None
            context.user_data.pop("card_subset", None)
            context.user_data.pop("card_letter_pending", None)
            context.user_data.pop("card_prompt_message_id", None)
            await _cleanup_preview_messages(update, context, q.message.message_id)
            text = (
                f"📘 Флэш-карточки — {setup['continent']}.\n"
                "Выбери подкатегорию."
            )
            try:
                await q.edit_message_text(
                    text, reply_markup=cards_subcategories_kb()
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to show subcategory menu: %s", exc)
            return
        return

    if action == "sub":
        await q.answer()
        if not setup:
            try:
                await q.edit_message_text(
                    "Сначала выберите континент.",
                    reply_markup=continent_kb("menu:cards"),
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to prompt continent selection: %s", exc)
            return
        option = parts[2] if len(parts) > 2 else ""
        setup["mode"] = "subsets"
        await _cleanup_preview_messages(update, context, q.message.message_id)
        if option == "matching":
            setup["subcategory"] = "matching"
            setup["letter"] = None
            context.user_data.pop("card_prompt_message_id", None)
            matches = select_matching_countries(setup["countries"])
            if not matches:
                text = (
                    "Таких стран нет в выбранном континенте."
                    "\nВыбери другую подкатегорию."
                )
                try:
                    await q.edit_message_text(
                        text, reply_markup=cards_subcategories_kb()
                    )
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to show empty matching notice: %s", exc)
                return
            title = (
                f"{setup['continent']} — совпадает со страной ({len(matches)}):\n"
            )
            if not await _show_preview(
                update, context, matches, title, "cards:back:subcategory"
            ):
                try:
                    await q.edit_message_text(
                        "Не удалось показать список. Попробуйте еще раз.",
                        reply_markup=cards_subcategories_kb(),
                    )
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to notify preview error: %s", exc)
            return
        if option == "letter":
            setup["subcategory"] = "letter"
            setup["letter"] = None
            context.user_data["card_letter_pending"] = True
            context.user_data.pop("card_subset", None)
            text = (
                f"📘 Флэш-карточки — {setup['continent']}.\n"
                "Введите букву, на которую начинается столица."
            )
            try:
                msg = await q.edit_message_text(
                    text, reply_markup=cards_subcategories_kb()
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to prompt for letter: %s", exc)
            else:
                context.user_data["card_prompt_message_id"] = msg.message_id
            return
        if option == "other":
            setup["subcategory"] = "other"
            setup["letter"] = None
            context.user_data.pop("card_prompt_message_id", None)
            matches = select_matching_countries(setup["countries"])
            others = select_remaining_countries(setup["countries"], matches)
            if not others:
                text = (
                    "Все столицы в этом континенте совпадают с названием страны."
                    "\nВыбери другую подкатегорию."
                )
                try:
                    await q.edit_message_text(
                        text, reply_markup=cards_subcategories_kb()
                    )
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to show empty other notice: %s", exc)
                return
            title = (
                f"{setup['continent']} — остальные столицы ({len(others)}):\n"
            )
            if not await _show_preview(
                update, context, others, title, "cards:back:subcategory"
            ):
                try:
                    await q.edit_message_text(
                        "Не удалось показать список. Попробуйте еще раз.",
                        reply_markup=cards_subcategories_kb(),
                    )
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to notify preview error: %s", exc)
            return
        return

    if action == "start":
        await q.answer()
        subset: list[str] | None = context.user_data.get("card_subset")
        if not subset:
            await q.answer("Список стран пуст. Выберите другую опцию.", show_alert=True)
            return
        await _cleanup_preview_messages(update, context, q.message.message_id)
        continent_filter = None
        if setup:
            continent_filter = setup.get("continent_filter")
        queue = [
            (country, random.choice(["country_to_capital", "capital_to_country"]))
            for country in subset
        ]
        random.shuffle(queue)
        if not queue:
            await q.answer("Список стран пуст. Выберите другую опцию.", show_alert=True)
            return
        session = CardSession(
            user_id=update.effective_user.id,
            continent_filter=continent_filter,
            mode="mixed",
            queue=queue,
        )
        context.user_data["card_session"] = session
        context.user_data.pop("card_letter_pending", None)
        context.user_data.pop("card_prompt_message_id", None)
        await _next_card(update, context)
        return

    session: CardSession | None = context.user_data.get("card_session")
    if not session or not hasattr(session, "current"):
        await q.answer()
        try:
            await q.edit_message_text(
                "Сессия не найдена. Нажмите /start, чтобы начать заново."
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify missing session: %s", e)
        return

    current = session.current

    if len(parts) == 3 and parts[1] == "opt":
        await q.answer()
        index = int(parts[2])
        item = (
            current["country"]
            if current["type"] == "country_to_capital"
            else current["capital"]
        )
        selected = current["options"][index]
        if selected == current["answer"]:
            if item not in session.unknown_set:
                get_user_stats(context.user_data).to_repeat.discard(item)
                session.stats["known"] += 1
            fact = get_static_fact(current["country"])
            text = (
                f"✅ Верно\n{current['country']}"
                f"\nСтолица: {current['capital']}"
            )
            fact_msg = (
                f"{text}\n\n{fact}\n\nНажми кнопку ниже, чтобы узнать еще один факт"
            )
            flag_path = get_flag_image_path(current["country"])
            try:
                await q.edit_message_reply_markup(None)
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to clear card buttons: %s", e)
            msg = None
            if flag_path:
                try:
                    with flag_path.open("rb") as flag_file:
                        msg = await context.bot.send_photo(
                            q.message.chat_id,
                            flag_file,
                            caption=fact_msg,
                            reply_markup=fact_more_kb(prefix="cards"),
                        )
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to send flag image: %s", e)
            else:
                try:
                    msg = await context.bot.send_message(
                        q.message.chat_id,
                        fact_msg,
                        reply_markup=fact_more_kb(prefix="cards"),
                    )
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to send card feedback: %s", e)
            if msg:
                session.fact_message_id = msg.message_id
                session.fact_subject = current["country"]
                session.fact_text = fact
        else:
            session.unknown_set.add(item)
            add_to_repeat(context.user_data, {item})
            try:
                await q.edit_message_reply_markup(None)
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to clear card buttons: %s", e)
            try:
                await context.bot.send_message(
                    q.message.chat_id,
                    (
                        "❌ <b>Неверно</b>."
                        f"\n\nПравильный ответ:\n<b>{current['answer']}</b>"
                    ),
                    parse_mode="HTML",
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send card feedback: %s", e)
        session.current_answered = True
        await asyncio.sleep(5)
        await _next_card(update, context, replace_message=False)
        return

    action = parts[1]
    if action == "more_fact":
        await q.answer()
        if session.fact_message_id != q.message.message_id:
            return
        extra = await generate_llm_fact(
            session.fact_subject or "",
            session.fact_text or "",
        )
        base = q.message.caption or q.message.text or ""
        base = base.replace(
            "\n\nНажми кнопку ниже, чтобы узнать еще один факт", ""
        )
        try:
            if q.message.photo:
                await q.edit_message_caption(
                    caption=f"{base}\n\nЕще один факт: {extra}", reply_markup=None
                )
            else:
                await q.edit_message_text(
                    f"{base}\n\nЕще один факт: {extra}", reply_markup=None
                )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send extra fact: %s", e)
        session.fact_message_id = None
        return

    if action == "show":
        await q.answer()
        item = (
            current["country"]
            if current["type"] == "country_to_capital"
            else current["capital"]
        )
        session.unknown_set.add(item)
        add_to_repeat(context.user_data, {item})
        try:
            await q.edit_message_reply_markup(None)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to clear card buttons: %s", e)
        text = f"{current['country']}\nСтолица: {current['capital']}"
        fact = get_static_fact(current["country"])
        fact_msg = (
            f"{text}\n\n{fact}\n\nНажми кнопку ниже, чтобы узнать еще один факт"
        )
        flag_path = get_flag_image_path(current["country"])
        msg = None
        if flag_path:
            try:
                with flag_path.open("rb") as flag_file:
                    msg = await context.bot.send_photo(
                        q.message.chat_id,
                        flag_file,
                        caption=fact_msg,
                        reply_markup=fact_more_kb(prefix="cards"),
                    )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send flag image: %s", e)
        else:
            try:
                msg = await context.bot.send_message(
                    q.message.chat_id,
                    fact_msg,
                    reply_markup=fact_more_kb(prefix="cards"),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send card feedback: %s", e)
        if msg:
            session.fact_message_id = msg.message_id
            session.fact_subject = current["country"]
            session.fact_text = fact
        session.current_answered = True
        await asyncio.sleep(5)
        await _next_card(update, context, replace_message=False)
        return

    if action == "next":
        await q.answer()
        await _next_card(update, context)
        return

    if action == "skip":
        await q.answer()
        item = (
            current["country"]
            if current["type"] == "country_to_capital"
            else current["capital"]
        )
        session.unknown_set.add(item)
        add_to_repeat(context.user_data, {item})
        session.current_answered = True
        await _next_card(update, context)
        return

    if action == "finish":
        await q.answer()
        await _finish_session(update, context)
        return

    if action == "repeat" and session.unknown_set:
        await q.answer()
        session.queue = list(session.unknown_set)
        random.shuffle(session.queue)
        session.unknown_set.clear()
        session.stats = {"shown": 0, "known": 0}
        await _next_card(update, context)
        return

    await q.answer()


async def msg_cards_letter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle letter input for the "capital by letter" subcategory."""

    if not context.user_data.get("card_letter_pending"):
        return

    message = update.effective_message
    text = (message.text or "").strip()

    setup: dict | None = context.user_data.get("card_setup")
    if not setup:
        context.user_data.pop("card_letter_pending", None)
        await message.reply_text(
            "Настройка карточек не найдена. Вернитесь в меню и выберите режим снова."
        )
        return

    if len(text) != 1 or not text.isalpha():
        await message.reply_text(
            "Пожалуйста, введите одну букву без цифр и символов."
        )
        return

    letter = text.upper()
    subset = select_countries_by_letter(setup["countries"], text)
    if not subset:
        await message.reply_text(
            "Столиц на эту букву не найдено. Попробуйте другую букву."
        )
        return

    prompt_id = context.user_data.get("card_prompt_message_id")
    keep_id = prompt_id if isinstance(prompt_id, int) else None
    await _cleanup_preview_messages(update, context, keep_id)

    setup["subcategory"] = "letter"
    setup["letter"] = letter

    title = (
        f"{setup['continent']} — столицы на букву {letter} ({len(subset)}):\n"
    )
    if not await _show_preview(
        update,
        context,
        subset,
        title,
        "cards:back:subcategory",
        origin_message_id=keep_id,
    ):
        await message.reply_text(
            "Не удалось показать список. Попробуйте выбрать подкатегорию еще раз."
        )
        return

    context.user_data["card_letter_pending"] = False
    context.user_data.pop("card_prompt_message_id", None)

