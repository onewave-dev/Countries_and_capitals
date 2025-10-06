import asyncio
import random
import logging

from telegram import Update
from telegram.error import TelegramError, BadRequest
from telegram.ext import ContextTypes
from httpx import HTTPError

# ``DATA`` is loaded in ``app`` which requires TELEGRAM_BOT_TOKEN to be set.
# During unit tests this environment variable may be missing, so fall back to
# ``None`` to avoid import-time errors.
try:  # pragma: no cover - best effort for missing token during tests
    from app import DATA
except RuntimeError:  # pragma: no cover - token not set
    DATA = None  # type: ignore
from .state import TestSession, add_to_repeat
from .keyboards import (
    cards_kb,
    cards_answer_kb,
    back_to_menu_kb,
    continent_kb,
    fact_more_kb,
    main_menu_kb,
    test_mode_kb,
    test_subcategories_kb,
    test_preview_kb,
)
from .questions import make_card_question
from .flags import get_country_flag, get_flag_image_path
from .facts import get_static_fact, generate_llm_fact
try:  # pragma: no cover - allow importing without configured token during tests
    from .handlers_menu import WELCOME, ADMIN_ID
except (RuntimeError, ImportError):
    WELCOME = "Привет!"
    ADMIN_ID = 0
from .subsets import (
    cleanup_preview_messages,
    select_countries_by_letter,
    select_matching_countries,
    select_remaining_countries,
    show_preview,
)

logger = logging.getLogger(__name__)

__all__ = ("cb_test", "msg_test_letter")
__test__ = False


async def _clear_test_prompt(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int
) -> None:
    """Delete the pending letter prompt message if it exists."""

    prompt_id = context.user_data.pop("test_prompt_message_id", None)
    if isinstance(prompt_id, int):
        try:
            await context.bot.delete_message(chat_id, prompt_id)
        except (TelegramError, HTTPError) as exc:
            logger.debug("Failed to delete test letter prompt %s: %s", prompt_id, exc)


async def _next_question(
    update: Update, context: ContextTypes.DEFAULT_TYPE, replace_message: bool = True
) -> None:
    """Send the next test question or finish if queue is empty."""

    session: TestSession = context.user_data["test_session"]
    if not session.queue:
        await _finish_session(update, context)
        return

    country = session.queue.pop(0)
    direction = random.choice(["country_to_capital", "capital_to_country"])
    item = country if direction == "country_to_capital" else DATA.capital_by_country[country]
    question = make_card_question(DATA, item, direction)
    session.current = question
    session.stats["total"] += 1

    logger.debug(
        "Generated test question for user %s: %s -> %s",
        session.user_id,
        question["prompt"],
        question["answer"],
    )

    if update.callback_query and replace_message:
        q = update.callback_query
        try:
            await q.edit_message_text(
                question["prompt"],
                reply_markup=cards_kb(question["options"], prefix="test"),
                parse_mode="HTML",
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send test question: %s", e)
            return
    else:
        chat_id = update.effective_chat.id
        try:
            await context.bot.send_message(
                chat_id,
                question["prompt"],
                reply_markup=cards_kb(question["options"], prefix="test"),
                parse_mode="HTML",
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send test question: %s", e)
            return


async def _finish_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Output final stats and unknown pairs."""

    session: TestSession | None = context.user_data.get("test_session")
    if not session:
        return

    text = f"{session.stats['correct']} правильных из {session.total_questions}"
    if session.unknown_set:
        lines = []
        for country in sorted(session.unknown_set):
            capital = DATA.capital_by_country.get(country, "")
            flag = get_country_flag(country)
            lines.append(f"{flag} {country} — {capital}")
        text += "\n\nОшибки или пропуски:\n" + "\n".join(lines)
    chat_id = update.effective_chat.id
    try:
        await context.bot.send_message(chat_id, text, reply_markup=back_to_menu_kb())
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to send test results: %s", e)
    context.user_data.pop("test_session", None)


async def cb_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all ``^test:`` callbacks."""

    q = update.callback_query
    parts = q.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if parts == ["test", "void"]:
        await q.answer()
        return

    if parts == ["test", "continent"]:
        await q.answer()
        await cleanup_preview_messages(update, context, "test", q.message.message_id)
        await _clear_test_prompt(context, q.message.chat_id)
        for key in (
            "test_session",
            "test_setup",
            "test_subset",
            "test_letter_pending",
        ):
            context.user_data.pop(key, None)
        try:
            await q.edit_message_text(
                "📝 Тест: выбери континент.",
                reply_markup=continent_kb("test", include_menu=True, include_world=False),
            )
        except (TelegramError, HTTPError) as exc:
            logger.warning("Failed to show test continent selection: %s", exc)
        return

    if parts == ["test", "random30"]:
        await q.answer()
        await cleanup_preview_messages(update, context, "test", q.message.message_id)
        await _clear_test_prompt(context, q.message.chat_id)
        for key in (
            "test_setup",
            "test_subset",
            "test_letter_pending",
        ):
            context.user_data.pop(key, None)
        countries = DATA.countries()
        queue = random.sample(countries, k=min(30, len(countries)))
        session = TestSession(user_id=update.effective_user.id, queue=queue)
        session.total_questions = len(queue)
        context.user_data["test_session"] = session
        await _next_question(update, context)
        return

    setup: dict | None = context.user_data.get("test_setup")

    if action == "menu":
        await q.answer()
        await cleanup_preview_messages(update, context, "test", q.message.message_id)
        await _clear_test_prompt(context, q.message.chat_id)
        for key in (
            "test_session",
            "test_setup",
            "test_subset",
            "test_letter_pending",
        ):
            context.user_data.pop(key, None)
        try:
            await q.edit_message_text(
                WELCOME,
                reply_markup=main_menu_kb(update.effective_user.id == ADMIN_ID),
            )
        except (TelegramError, HTTPError) as exc:
            logger.warning("Failed to return to menu from test: %s", exc)
        return

    if action == "back":
        await q.answer()
        target = parts[2] if len(parts) > 2 else ""
        await cleanup_preview_messages(update, context, "test", q.message.message_id)
        if target == "continent":
            await _clear_test_prompt(context, q.message.chat_id)
            for key in (
                "test_session",
                "test_setup",
                "test_subset",
                "test_letter_pending",
            ):
                context.user_data.pop(key, None)
            try:
                await q.edit_message_text(
                    "📝 Тест: выбери континент.",
                    reply_markup=continent_kb(
                        "test", include_menu=True, include_world=False
                    ),
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to show test continent selection: %s", exc)
            return
        if not setup:
            try:
                await q.edit_message_text(
                    "Выбор континента не найден. Нажмите /start, чтобы начать заново.",
                    reply_markup=main_menu_kb(update.effective_user.id == ADMIN_ID),
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to handle missing test setup: %s", exc)
            return
        context.user_data.pop("test_subset", None)
        context.user_data.pop("test_letter_pending", None)
        await _clear_test_prompt(context, q.message.chat_id)
        if target == "mode":
            text = (
                f"📝 Тест — {setup['continent']}.\n"
                "Выбери, как будем тестироваться."
            )
            try:
                await q.edit_message_text(text, reply_markup=test_mode_kb())
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to show test mode selection: %s", exc)
            return
        if target == "subcategory":
            text = (
                f"📝 Тест — {setup['continent']}.\n"
                "Выбери подкатегорию."
            )
            try:
                await q.edit_message_text(text, reply_markup=test_subcategories_kb())
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to show test subcategories: %s", exc)
            return
        return

    if action == "mode":
        await q.answer()
        if not setup:
            try:
                await q.edit_message_text(
                    "Сначала выберите континент.",
                    reply_markup=continent_kb("test", include_menu=True, include_world=False),
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to prompt test continent: %s", exc)
            return
        option = parts[2] if len(parts) > 2 else ""
        if option == "all":
            setup["mode"] = "all"
            setup["subcategory"] = None
            setup["letter"] = None
            await cleanup_preview_messages(update, context, "test", q.message.message_id)
            await _clear_test_prompt(context, q.message.chat_id)
            subset = setup["countries"]
            title = f"{setup['continent']} — все страны ({len(subset)}):\n"
            if not await show_preview(
                update,
                context,
                subset,
                title,
                "test:back:mode",
                "test",
                test_preview_kb,
            ):
                try:
                    await q.edit_message_text(
                        "Не удалось подготовить список. Попробуйте выбрать другую опцию.",
                        reply_markup=test_mode_kb(),
                    )
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to notify test preview error: %s", exc)
            return
        if option == "subsets":
            setup["mode"] = "subsets"
            setup["subcategory"] = None
            setup["letter"] = None
            context.user_data.pop("test_subset", None)
            context.user_data.pop("test_letter_pending", None)
            await _clear_test_prompt(context, q.message.chat_id)
            await cleanup_preview_messages(update, context, "test", q.message.message_id)
            text = (
                f"📝 Тест — {setup['continent']}.\n"
                "Выбери подкатегорию."
            )
            try:
                await q.edit_message_text(text, reply_markup=test_subcategories_kb())
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to show test subcategories: %s", exc)
            return
        return

    if action == "sub":
        await q.answer()
        if not setup:
            try:
                await q.edit_message_text(
                    "Сначала выберите континент.",
                    reply_markup=continent_kb("test", include_menu=True, include_world=False),
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to prompt test continent: %s", exc)
            return
        option = parts[2] if len(parts) > 2 else ""
        setup["mode"] = "subsets"
        await cleanup_preview_messages(update, context, "test", q.message.message_id)
        if option == "matching":
            setup["subcategory"] = "matching"
            setup["letter"] = None
            await _clear_test_prompt(context, q.message.chat_id)
            matches = select_matching_countries(setup["countries"])
            if not matches:
                text = (
                    "Таких стран нет в выбранном континенте."
                    "\nВыбери другую подкатегорию."
                )
                try:
                    await q.edit_message_text(text, reply_markup=test_subcategories_kb())
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to show empty matching notice: %s", exc)
                return
            title = (
                f"{setup['continent']} — совпадает со страной ({len(matches)}):\n"
            )
            if not await show_preview(
                update,
                context,
                matches,
                title,
                "test:back:subcategory",
                "test",
                test_preview_kb,
            ):
                try:
                    await q.edit_message_text(
                        "Не удалось показать список. Попробуйте еще раз.",
                        reply_markup=test_subcategories_kb(),
                    )
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to notify test preview error: %s", exc)
            return
        if option == "letter":
            setup["subcategory"] = "letter"
            setup["letter"] = None
            context.user_data["test_letter_pending"] = True
            context.user_data.pop("test_subset", None)
            await _clear_test_prompt(context, q.message.chat_id)
            text = (
                f"📝 Тест — {setup['continent']}.\n"
                "Введите букву, на которую начинается столица."
            )
            try:
                msg = await context.bot.send_message(
                    q.message.chat_id,
                    text,
                )
            except (TelegramError, HTTPError) as exc:
                logger.warning("Failed to prompt test letter: %s", exc)
            else:
                context.user_data["test_prompt_message_id"] = msg.message_id
            return
        if option == "other":
            setup["subcategory"] = "other"
            setup["letter"] = None
            await _clear_test_prompt(context, q.message.chat_id)
            matches = select_matching_countries(setup["countries"])
            others = select_remaining_countries(setup["countries"], matches)
            if not others:
                text = (
                    "Все столицы в этом континенте совпадают с названием страны."
                    "\nВыбери другую подкатегорию."
                )
                try:
                    await q.edit_message_text(text, reply_markup=test_subcategories_kb())
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to show empty other notice: %s", exc)
                return
            title = (
                f"{setup['continent']} — остальные столицы ({len(others)}):\n"
            )
            if not await show_preview(
                update,
                context,
                others,
                title,
                "test:back:subcategory",
                "test",
                test_preview_kb,
            ):
                try:
                    await q.edit_message_text(
                        "Не удалось показать список. Попробуйте еще раз.",
                        reply_markup=test_subcategories_kb(),
                    )
                except (TelegramError, HTTPError) as exc:
                    logger.warning("Failed to notify test preview error: %s", exc)
            return
        return

    if action == "start":
        await q.answer()
        subset: list[str] | None = context.user_data.get("test_subset")
        if not subset:
            await q.answer("Список стран пуст. Выберите другую опцию.", show_alert=True)
            return
        await cleanup_preview_messages(update, context, "test", q.message.message_id)
        queue = list(subset)
        random.shuffle(queue)
        if not queue:
            await q.answer("Список стран пуст. Выберите другую опцию.", show_alert=True)
            return
        session = TestSession(user_id=update.effective_user.id, queue=queue)
        session.total_questions = len(queue)
        context.user_data["test_session"] = session
        context.user_data.pop("test_letter_pending", None)
        context.user_data.pop("test_prompt_message_id", None)
        await _next_question(update, context)
        return

    reserved = {
        "opt",
        "show",
        "skip",
        "next",
        "finish",
        "more_fact",
        "mode",
        "sub",
        "back",
        "start",
        "menu",
        "continent",
        "random30",
    }
    if len(parts) == 2 and parts[0] == "test" and action not in reserved:
        await q.answer()
        continent = parts[1]
        countries = DATA.countries(continent if continent != "Весь мир" else None)
        setup_data = {
            "continent": continent,
            "continent_filter": None if continent == "Весь мир" else continent,
            "countries": countries,
            "mode": None,
            "subcategory": None,
            "letter": None,
        }
        context.user_data["test_setup"] = setup_data
        context.user_data.pop("test_subset", None)
        context.user_data.pop("test_session", None)
        context.user_data.pop("test_letter_pending", None)
        await _clear_test_prompt(context, q.message.chat_id)
        await cleanup_preview_messages(update, context, "test", q.message.message_id)
        text = (
            f"📝 Тест — {continent}.\n"
            "Выбери, как будем тестироваться."
        )
        try:
            await q.edit_message_text(text, reply_markup=test_mode_kb())
        except (TelegramError, HTTPError) as exc:
            logger.warning("Failed to show test mode selection: %s", exc)
        return

    session: TestSession | None = context.user_data.get("test_session")
    if not session or not hasattr(session, "current"):
        await q.answer()
        try:
            await q.edit_message_text(
                "Сессия не найдена. Нажмите /start, чтобы начать заново.",
                reply_markup=back_to_menu_kb(),
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify missing session: %s", e)
        return

    current = session.current
    if parts[1] == "opt":
        await q.answer()
        index = int(parts[2])
        selected = current["options"][index]
        try:
            await q.edit_message_reply_markup(None)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to clear test buttons: %s", e)
        if selected == current["answer"]:
            session.stats["correct"] += 1
            progress = (
                "✅ Верно. (Правильных ответов: "
                f"{session.stats['correct']} из {session.total_questions}. "
                f"Осталось вопросов {len(session.queue)})"
            )
            fact = get_static_fact(current["country"])
            text = f"{current['country']}\nСтолица: {current['capital']}"
            fact_msg = (
                f"{progress}\n\n{text}\n\n{fact}\n\nНажми кнопку ниже, чтобы узнать еще один факт"
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
                            reply_markup=fact_more_kb(prefix="test"),
                        )
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to send flag image: %s", e)
            else:
                try:
                    msg = await context.bot.send_message(
                        q.message.chat_id,
                        fact_msg,
                        reply_markup=fact_more_kb(prefix="test"),
                    )
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to send card feedback: %s", e)
            if msg:
                session.fact_message_id = msg.message_id
                session.fact_subject = current["country"]
                session.fact_text = fact
        else:
            session.unknown_set.add(current["country"])
            text = (
                "❌ <b>Неверно</b>."
                f"\n\nПравильный ответ:\n<b>{current['answer']}</b>"
            )
            try:
                await context.bot.send_message(q.message.chat_id, text, parse_mode="HTML")
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send test feedback: %s", e)
        await asyncio.sleep(4)
        await _next_question(update, context, replace_message=False)
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
            "\n\nНажми кнопку ниже, чтобы узнать еще один факт",
            "",
        )
        try:
            if q.message.photo:
                await q.edit_message_caption(
                    caption=f"{base}\n\nЕще один факт: {extra}",
                    reply_markup=None,
                )
            else:
                await q.edit_message_text(
                    f"{base}\n\nЕще один факт: {extra}",
                    reply_markup=None,
                )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send extra fact: %s", e)
        session.fact_message_id = None
        return
    if action == "show":
        await q.answer()
        item = current["country"]
        session.unknown_set.add(item)
        add_to_repeat(context.user_data, {item})
        try:
            await q.edit_message_reply_markup(None)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to clear test buttons: %s", e)
        fact = get_static_fact(current["country"])
        text = f"{current['country']}\nСтолица: {current['capital']}"
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
                        reply_markup=fact_more_kb(prefix="test"),
                    )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send flag image: %s", e)
        else:
            try:
                msg = await context.bot.send_message(
                    q.message.chat_id,
                    fact_msg,
                    reply_markup=fact_more_kb(prefix="test"),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send card feedback: %s", e)
        if msg:
            session.fact_message_id = msg.message_id
            session.fact_subject = current["country"]
            session.fact_text = fact
        await asyncio.sleep(4)
        await _next_question(update, context, replace_message=False)
        return

    if action == "next":
        await q.answer()
        await _next_question(update, context)
        return

    if action == "skip":
        await q.answer()
        item = current["country"]
        session.unknown_set.add(item)
        add_to_repeat(context.user_data, {item})
        await _next_question(update, context)
        return

    if action == "finish":
        await q.answer()
        await _finish_session(update, context)
        return

    await q.answer()


async def msg_test_letter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle letter input for the "capital by letter" test subcategory."""

    if not context.user_data.get("test_letter_pending"):
        return

    message = update.effective_message
    text = (message.text or "").strip()

    setup: dict | None = context.user_data.get("test_setup")
    if not setup:
        context.user_data.pop("test_letter_pending", None)
        await message.reply_text(
            "Настройка теста не найдена. Вернитесь в меню и выберите режим снова."
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

    prompt_id = context.user_data.get("test_prompt_message_id")
    keep_id = prompt_id if isinstance(prompt_id, int) else None
    await cleanup_preview_messages(update, context, "test", keep_id)

    title = (
        f"{setup['continent']} — столицы на букву {letter} ({len(subset)}):\n"
    )
    if not await show_preview(
        update,
        context,
        subset,
        title,
        "test:back:subcategory",
        "test",
        test_preview_kb,
        origin_message_id=keep_id,
    ):
        await message.reply_text(
            "Не удалось показать список. Попробуйте выбрать подкатегорию еще раз."
        )
        return

    setup["letter"] = letter
    context.user_data["test_letter_pending"] = False
    context.user_data.pop("test_prompt_message_id", None)
