"""Handlers for the cooperative two-versus-bot mode."""

from __future__ import annotations

import asyncio
import html
import os
import random
import uuid
import logging
from io import BytesIO
from typing import Dict, Tuple
from html import escape

from telegram import (
    Update,
    ReplyKeyboardRemove,
    Chat,
    User,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from httpx import HTTPError

from app import DATA
from .state import CoopSession
from .questions import make_card_question
from .keyboards import (
    coop_answer_kb,
    coop_join_kb,
    coop_invite_kb,
    coop_difficulty_kb,
    coop_continent_kb,
    coop_fact_more_kb,
    coop_finish_kb,
)
from .flags import get_flag_image_path
from .facts import get_static_fact, generate_llm_fact

logger = logging.getLogger(__name__)

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DUMMY_PLAYER_ID = -1
try:
    DUMMY_ACCURACY = float(os.getenv("DUMMY_ACCURACY", "0.7"))
except ValueError:
    DUMMY_ACCURACY = 0.7

# Probability of the bot answering correctly depending on the difficulty.
ACCURACY = {"easy": 0.7, "medium": 0.8, "hard": 0.9}

# Additional delay before showing every question in cooperative games.
EXTRA_QUESTION_DELAY = 4
FIRST_QUESTION_DELAY = 4 + EXTRA_QUESTION_DELAY
NEXT_QUESTION_DELAY = 2 + EXTRA_QUESTION_DELAY


# ===== Helpers =====


def _get_sessions(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, CoopSession]:
    """Return cooperative sessions stored in the current chat."""

    return context.chat_data.setdefault("sessions", {})


def _iter_session_maps(
    context: ContextTypes.DEFAULT_TYPE,
) -> list[Dict[str, CoopSession]]:
    """Return unique session mappings from all known chats."""

    seen: set[int] = set()
    mappings: list[Dict[str, CoopSession]] = []

    chat_data = getattr(context, "chat_data", None)
    if isinstance(chat_data, dict):
        current = chat_data.get("sessions")
        if isinstance(current, dict):
            mappings.append(current)
            seen.add(id(current))

    application = getattr(context, "application", None)
    app_chat_data = getattr(application, "chat_data", None)
    if isinstance(app_chat_data, dict):
        for data in app_chat_data.values():
            if not isinstance(data, dict):
                continue
            sessions = data.get("sessions")
            if isinstance(sessions, dict) and id(sessions) not in seen:
                mappings.append(sessions)
                seen.add(id(sessions))

    return mappings


def _find_session_global(
    context: ContextTypes.DEFAULT_TYPE, session_id: str
) -> CoopSession | None:
    """Find a cooperative session by identifier across chats."""

    for sessions in _iter_session_maps(context):
        session = sessions.get(session_id)
        if session:
            return session
    return None


def _remove_session(
    context: ContextTypes.DEFAULT_TYPE, session: CoopSession
) -> None:
    """Remove ``session`` from every chat's storage."""

    for sessions in _iter_session_maps(context):
        sessions.pop(session.session_id, None)


def _find_user_session(
    sessions: Dict[str, CoopSession], user_id: int
) -> Tuple[str, CoopSession] | tuple[None, None]:
    for sid, sess in sessions.items():
        if user_id in sess.players:
            return sid, sess
    return None, None


def _find_user_session_global(
    context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> Tuple[str, CoopSession] | tuple[None, None]:
    """Locate a session that already involves ``user_id``."""

    for sessions in _iter_session_maps(context):
        sid, session = _find_user_session(sessions, user_id)
        if session:
            return sid, session
    return None, None


async def _start_game(context: ContextTypes.DEFAULT_TYPE, session: CoopSession) -> None:
    """Prepare the question queue and send an intro before the first question."""

    countries = DATA.countries(session.continent_filter)
    if session.continent_filter is None:
        countries = random.sample(countries, k=min(30, len(countries)))
    session.remaining_pairs = []
    for country in countries:
        mode = random.choice(["country_to_capital", "capital_to_country"])
        item = (
            country if mode == "country_to_capital" else DATA.capital_by_country[country]
        )
        q = make_card_question(DATA, item, mode, session.continent_filter)
        session.remaining_pairs.append(q)
    random.shuffle(session.remaining_pairs)
    session.current_pair = None
    session.turn_index = 0
    session.player_stats = {pid: 0 for pid in session.players}
    session.bot_stats = 0
    session.total_pairs = len(session.remaining_pairs)
    session.fact_message_ids.clear()
    session.fact_subject = None
    session.fact_text = None

    intro_text = (
        "Игра начинается!\n"
        f"Всего вопросов: {session.total_pairs}.\n"
        "Игроки отвечают по очереди, затем бот.\n"
        "Команда игроков побеждает, если наберёт больше очков, чем бот.\n"
        "При равенстве очков будет ничья."
    )
    for pid in session.players:
        chat_id = session.player_chats.get(pid)
        if not chat_id:
            continue
        try:
            await context.bot.send_message(chat_id, intro_text)
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send coop intro: %s", e)

    logger.debug(
        "Delaying first cooperative question for session %s by %s seconds",
        session.session_id,
        FIRST_QUESTION_DELAY,
    )
    await asyncio.sleep(FIRST_QUESTION_DELAY)
    await _ask_current_pair(context, session)


def _is_flag_emoji(value: str) -> bool:
    """Return ``True`` if ``value`` looks like a regional flag emoji."""

    if len(value) != 2:
        return False
    return all(0x1F1E6 <= ord(char) <= 0x1F1FF for char in value)


def _split_flag_answer(option: str | None) -> tuple[str, str]:
    """Split ``option`` into (flag, text) components."""

    if not option:
        return "", ""

    option = option.strip()

    parts = option.split(" ", 1)
    if len(parts) == 2 and _is_flag_emoji(parts[0]):
        return parts[0], parts[1]
    return "", option


def _format_bot_wrong_answer(pair: dict | None, answer: str | None) -> str:
    """Return a formatted notification about bot's incorrect answer."""

    if pair is None:
        return "Бот-противник ответил.  Ответ неверный."

    if not answer:
        options = pair.get("options") or []
        if options:
            answer = options[0]
        else:
            answer = ""

    question_type = pair.get("type")
    if question_type == "country_to_capital":
        answer_text = f"<b>{html.escape(str(answer))}</b>" if answer else ""
    else:
        flag, title = _split_flag_answer(str(answer))
        parts: list[str] = []
        if flag:
            parts.append(flag)
        if title:
            parts.append(f"<b>{html.escape(title)}</b>")
        answer_text = " ".join(parts).strip()
        if not answer_text and answer:
            answer_text = f"<b>{html.escape(str(answer))}</b>"

    if not answer_text:
        answer_text = "<b>—</b>"

    return f"Бот-противник ответил {answer_text}.  Ответ неверный."


async def _auto_answer_dummy(
    context: ContextTypes.DEFAULT_TYPE, session: CoopSession
) -> None:
    """Automatically answer for the dummy teammate and advance the game."""

    if not session.current_pair:
        return

    should_answer_correct = random.random() < DUMMY_ACCURACY
    correct_option = session.current_pair["correct"]
    if should_answer_correct:
        chosen_option = correct_option
    else:
        other_options = [
            option for option in session.current_pair["options"] if option != correct_option
        ]
        if other_options:
            chosen_option = random.choice(other_options)
        else:
            chosen_option = correct_option
            should_answer_correct = True

    name = session.player_names.get(DUMMY_PLAYER_ID, "Бот-помощник")
    if should_answer_correct:
        projected = sum(session.player_stats.values()) + session.bot_stats + 1
        await _broadcast_correct_answer(context, session, name, projected)
    else:
        text = f"{name} отвечает неверно ({chosen_option})."

        for pid in session.players:
            chat_id = session.player_chats.get(pid)
            if not chat_id:
                continue
            try:
                await context.bot.send_message(chat_id, text, parse_mode="HTML")
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send dummy answer summary: %s", e)

    await _next_turn(context, session, should_answer_correct)


async def _ask_current_pair(context: ContextTypes.DEFAULT_TYPE, session: CoopSession) -> None:
    """Broadcast the current question to every participant."""

    if not session.current_pair:
        if not session.remaining_pairs:
            await _finish_game(context, session)
            return
        session.current_pair = session.remaining_pairs[0]

    current_player = session.players[session.turn_index]
    question_text = session.current_pair["prompt"]

    if current_player == DUMMY_PLAYER_ID:
        recipients = [pid for pid in session.players if pid != DUMMY_PLAYER_ID]
    else:
        recipients = [current_player] + [pid for pid in session.players if pid != current_player]

    for pid in recipients:
        chat_id = session.player_chats.get(pid)
        if not chat_id:
            continue
        reply_markup = None
        if pid == current_player:
            reply_markup = coop_answer_kb(
                session.session_id, current_player, session.current_pair["options"]
            )
        try:
            msg = await context.bot.send_message(
                chat_id,
                question_text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            if pid == current_player:
                session.question_message_ids[current_player] = msg.message_id
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send coop question: %s", e)

    if current_player == DUMMY_PLAYER_ID:
        await _auto_answer_dummy(context, session)


async def _broadcast_correct_answer(
    context: ContextTypes.DEFAULT_TYPE,
    session: CoopSession,
    name: str,
    projected_total: int | None = None,
) -> None:
    """Send a notification about a correct answer with progress and a fact."""

    pair = session.current_pair
    if not pair:
        return

    country = pair.get("country", "")
    capital = pair.get("capital", "")

    fact = get_static_fact(country)
    header = f"✅ {name} отвечает верно."
    body = (
        f"{country}\nСтолица: {capital}\n\n{fact}\n\n"
        "Нажми кнопку ниже, чтобы узнать еще один факт"
    )
    caption_text = f"{header}\n\n{body}"

    flag_path = get_flag_image_path(country)
    flag_bytes: bytes | None = None
    if flag_path:
        try:
            flag_bytes = flag_path.read_bytes()
        except OSError as exc:
            logger.warning("Failed to read flag image for %s: %s", country, exc)
            flag_bytes = None

    session.fact_message_ids.clear()
    session.fact_subject = country
    session.fact_text = fact
    kb = coop_fact_more_kb(session.session_id)

    for pid in session.players:
        chat_id = session.player_chats.get(pid)
        if not chat_id:
            continue
        try:
            msg = None
            if flag_bytes is not None and flag_path is not None:
                photo = BytesIO(flag_bytes)
                photo.name = flag_path.name
                msg = await context.bot.send_photo(
                    chat_id, photo=photo, caption=caption_text, reply_markup=kb
                )
            else:
                msg = await context.bot.send_message(
                    chat_id, caption_text, reply_markup=kb, parse_mode="HTML"
                )
            if msg:
                session.fact_message_ids[pid] = msg.message_id
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send correct answer summary: %s", e)


def _format_team_label(session: CoopSession) -> str:
    """Return a readable team label based on registered players."""

    player_names: list[str] = []
    for index, pid in enumerate(session.players, start=1):
        name = session.player_names.get(pid)
        if not name:
            name = f"Игрок {index}"
        player_names.append(name)

    if not player_names:
        return "Игроки"
    if len(player_names) == 1:
        return player_names[0]
    if len(player_names) == 2:
        return f"{player_names[0]} и {player_names[1]}"
    return ", ".join(player_names[:-1]) + f" и {player_names[-1]}"


def _format_remaining_questions_line(count: int) -> str:
    """Return a formatted string describing how many questions remain."""

    remainder_10 = count % 10
    remainder_100 = count % 100
    if remainder_10 == 1 and remainder_100 != 11:
        word = "вопрос"
    elif 2 <= remainder_10 <= 4 and remainder_100 not in (12, 13, 14):
        word = "вопроса"
    else:
        word = "вопросов"
    return f"❓ Осталось <b>{count}</b> {word}"


async def _broadcast_score(
    context: ContextTypes.DEFAULT_TYPE, session: CoopSession
) -> None:
    """Send the current team vs bot score to all players."""

    team_label = _format_team_label(session)
    team_label_html = escape(team_label)
    players_total = sum(session.player_stats.values())
    answered_total = players_total + session.bot_stats
    remaining = max(session.total_pairs - answered_total, 0)
    remaining_line = _format_remaining_questions_line(remaining)
    text = (
        "📊 <b>Текущий счёт</b>\n"
        f"🤝 <b>Команда</b> ({team_label_html}) — <b>{players_total}</b>\n"
        f"🤖 <b>Бот-противник</b> — <b>{session.bot_stats}</b>\n"
        f"{remaining_line}"
    )

    for pid in session.players:
        chat_id = session.player_chats.get(pid)
        if not chat_id:
            continue
        try:
            await context.bot.send_message(chat_id, text, parse_mode="HTML")
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to broadcast coop score: %s", e)


async def _next_turn(
    context: ContextTypes.DEFAULT_TYPE, session: CoopSession, correct: bool
) -> None:
    """Advance to the next turn. Handles bot moves when needed."""

    if not session.players:
        return

    current_player = session.players[session.turn_index]

    score_changed = False

    if correct:
        session.player_stats[current_player] = session.player_stats.get(current_player, 0) + 1
        score_changed = True
        if session.remaining_pairs:
            session.remaining_pairs.pop(0)
        session.current_pair = None

    session.turn_index += 1

    if session.turn_index == len(session.players):
        if not session.current_pair and session.remaining_pairs:
            session.current_pair = session.remaining_pairs[0]
        if not session.current_pair:
            session.turn_index = 0
            await _finish_game(context, session)
            return

        bot_accuracy = ACCURACY.get(session.difficulty, 0.7)
        bot_correct = random.random() < bot_accuracy
        if bot_correct:
            session.bot_stats += 1
            score_changed = True
            await _broadcast_correct_answer(context, session, "Бот")
        else:
            pair = session.current_pair if isinstance(session.current_pair, dict) else None
            bot_answer: str | None = None
            if pair:
                options = list(pair.get("options") or [])
                correct_option = pair.get("correct")
                wrong_options = [opt for opt in options if opt != correct_option]
                if wrong_options:
                    bot_answer = random.choice(wrong_options)
                elif options:
                    bot_answer = options[0]
            text = _format_bot_wrong_answer(pair, bot_answer)

            for pid in session.players:
                chat_id = session.player_chats.get(pid)
                if not chat_id:
                    continue
                try:
                    await context.bot.send_message(chat_id, text, parse_mode="HTML")
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to notify about bot move: %s", e)
        if bot_correct:
            if session.remaining_pairs:
                session.remaining_pairs.pop(0)
            session.current_pair = None
        session.turn_index = 0

    if score_changed:
        await _broadcast_score(context, session)

    if not session.remaining_pairs:
        await _finish_game(context, session)
        return

    logger.debug(
        "Delaying next cooperative question for session %s by %s seconds",
        session.session_id,
        NEXT_QUESTION_DELAY,
    )
    await asyncio.sleep(NEXT_QUESTION_DELAY)
    if session.remaining_pairs:
        await _ask_current_pair(context, session)
        return

    await _finish_game(context, session)


async def _finish_game(context: ContextTypes.DEFAULT_TYPE, session: CoopSession) -> None:
    """Send final statistics and remove the session."""

    _remove_session(context, session)
    team_label = _format_team_label(session)
    team_label_html = escape(team_label)
    players_total = sum(session.player_stats.values())
    team_line = (
        f"🤝 <b>Команда</b> ({team_label_html}) — <b>{players_total}</b>"
    )
    bot_line = f"🤖 <b>Бот-противник</b> — <b>{session.bot_stats}</b>"
    if players_total > session.bot_stats:
        result_line = f"🎉 <b>Команда ({team_label_html}) побеждает!</b>"
    elif players_total < session.bot_stats:
        result_line = "🤖 <b>Бот-противник одерживает победу!</b>"
    else:
        result_line = "🤝 <b>Ничья — отличная игра!</b>"

    text = (
        "🏁 <b>Игра завершена!</b>\n"
        f"{team_line}\n"
        f"{bot_line}\n\n"
        f"{result_line}"
    )
    keyboard = coop_finish_kb()
    for pid in session.players:
        chat_id = session.player_chats.get(pid)
        if not chat_id:
            continue
        try:
            await context.bot.send_message(
                chat_id, text, parse_mode="HTML", reply_markup=keyboard
            )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to send coop final result: %s", e)


# ===== Command handlers =====


async def cmd_coop_capitals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a new cooperative match and request player's name."""

    chat = update.effective_chat
    user = update.effective_user

    if chat.type != "private":
        try:
            if update.message:
                await update.message.reply_text(
                    "Команду /coop_capitals можно использовать только в личке."
                )
            else:
                await context.bot.send_message(
                    chat.id, "Команду /coop_capitals можно использовать только в личке."
                )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify coop_capitals restriction: %s", e)
        return

    sessions = _get_sessions(context)
    _, existing = _find_user_session_global(context, user.id)
    if existing:
        try:
            if update.message:
                await update.message.reply_text(
                    "У вас уже есть активный матч. Используйте /coop_cancel для отмены."
                )
            else:
                await context.bot.send_message(
                    chat.id,
                    "У вас уже есть активный матч. Используйте /coop_cancel для отмены.",
                )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify existing coop match: %s", e)
        return

    session_id = uuid.uuid4().hex[:8]
    session = CoopSession(session_id=session_id)
    session.players.append(user.id)
    session.player_chats[user.id] = chat.id
    selected_continent = context.user_data.get("continent")
    if selected_continent:
        session.continent_label = selected_continent
        session.continent_filter = (
            None if selected_continent == "Весь мир" else selected_continent
        )
    sessions[session_id] = session
    context.user_data["coop_pending"] = {"session_id": session_id, "stage": "name"}

    try:
        if update.message:
            await update.message.reply_text("Матч создан. Как вас зовут?")
        else:
            await context.bot.send_message(chat.id, "Матч создан. Как вас зовут?")
    except (TelegramError, HTTPError) as e:
        logger.warning("Failed to request player name: %s", e)


async def cmd_coop_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Join an existing cooperative match by its session id."""

    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "Команду /coop_join можно использовать только в личке."
        )
        return

    if not context.args:
        await update.message.reply_text("Использование: /coop_join <код>")
        return

    session_id = context.args[0]
    sessions = _get_sessions(context)
    session = _find_session_global(context, session_id)
    if not session:
        await update.message.reply_text("Матч не найден")
        return

    sessions[session_id] = session
    user_id = update.effective_user.id
    if user_id in session.players:
        await update.message.reply_text("Вы уже участвуете в этом матче")
        return
    if len(session.players) >= 2:
        await update.message.reply_text("В матче уже хватает игроков")
        return

    session.players.append(user_id)
    session.player_chats[user_id] = update.effective_chat.id
    context.user_data["coop_pending"] = {"session_id": session_id, "stage": "name"}

    await update.message.reply_text("Введите ваше имя")


async def cmd_coop_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel the current cooperative match for the user."""

    _get_sessions(context)
    _, session = _find_user_session_global(context, update.effective_user.id)
    if not session:
        await update.message.reply_text("Активных матчей не найдено")
        return

    _remove_session(context, session)
    for pid in session.players:
        chat_id = session.player_chats.get(pid)
        if not chat_id:
            continue
        try:
            if pid == update.effective_user.id:
                await context.bot.send_message(chat_id, "Матч отменён")
            else:
                await context.bot.send_message(
                    chat_id, "Соперник покинул матч. Игра отменена"
                )
        except (TelegramError, HTTPError) as e:
            logger.warning("Failed to notify match cancel: %s", e)


async def cmd_coop_test(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: User | None = None,
    chat: Chat | None = None,
) -> None:
    """Admin-only helper command to quickly start a match."""

    user = user or update.effective_user
    chat = chat or update.effective_chat

    if not user or user.id != ADMIN_ID:
        return

    sessions = _get_sessions(context)
    session_id = uuid.uuid4().hex[:8]
    session = CoopSession(session_id=session_id, difficulty="medium")
    human_id = user.id
    human_chat_id = chat.id if chat else None
    session.players = [human_id, DUMMY_PLAYER_ID]
    if human_chat_id is not None:
        session.player_chats = {human_id: human_chat_id}
    session.player_names = {
        human_id: getattr(user, "full_name", None) or "Тестер",
        DUMMY_PLAYER_ID: "Бот-помощник",
    }
    selected_continent = context.user_data.get("continent")
    if selected_continent:
        session.continent_label = selected_continent
        session.continent_filter = (
            None if selected_continent == "Весь мир" else selected_continent
        )
    sessions[session_id] = session

    await _start_game(context, session)


# ===== Message & callback handlers =====


async def msg_coop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages for cooperative mode (name entry)."""

    pending = context.user_data.get("coop_pending")
    if not pending:
        return

    session_id = pending.get("session_id")
    stage = pending.get("stage")
    sessions = _get_sessions(context)
    session = sessions.get(session_id)
    if not session:
        session = _find_session_global(context, session_id)
        if not session:
            context.user_data.pop("coop_pending", None)
            return
        sessions[session_id] = session

    user_id = update.effective_user.id

    if stage == "name":
        if not update.message or not update.message.text:
            await update.message.reply_text("Пожалуйста, отправьте имя текстом")
            return
        session.player_names[user_id] = update.message.text.strip()
        if len(session.players) == 1:
            pending["stage"] = "invite"
            await update.message.reply_text(
                "Имя сохранено. Пригласите второго игрока.",
                reply_markup=coop_invite_kb(),
            )
        else:
            context.user_data.pop("coop_pending", None)
            if session.continent_filter is not None or session.continent_label:
                continent_name = (
                    session.continent_label
                    or session.continent_filter
                    or "Весь мир"
                )
                await update.message.reply_text(
                    (
                        "Имя сохранено. Континент: "
                        f"{continent_name}. Выберите сложность соперника."
                    ),
                    reply_markup=coop_difficulty_kb(session_id, user_id),
                )
                for pid in session.players:
                    if pid == user_id:
                        continue
                    chat_id = session.player_chats.get(pid)
                    if not chat_id:
                        continue
                    try:
                        await context.bot.send_message(
                            chat_id,
                            (
                                "Второй игрок присоединился. Континент: "
                                f"{continent_name}. Выберите сложность соперника."
                            ),
                            reply_markup=coop_difficulty_kb(session_id, pid),
                        )
                    except (TelegramError, HTTPError) as e:
                        logger.warning(
                            "Failed to send difficulty selection: %s", e
                        )
            else:
                await update.message.reply_text(
                    "Имя сохранено. Выберите континент.",
                    reply_markup=coop_continent_kb(session_id),
                )
                first_player = session.players[0]
                first_chat = session.player_chats[first_player]
                await context.bot.send_message(
                    first_chat,
                    "Второй игрок присоединился. Выберите континент.",
                    reply_markup=coop_continent_kb(session_id),
                )

    elif stage == "invite":
        message = update.message
        if not message:
            return

        user_shared = getattr(message, "user_shared", None)
        shared_user_id = getattr(user_shared, "user_id", None) if user_shared else None
        contact = getattr(message, "contact", None)
        contact_user_id = getattr(contact, "user_id", None) if contact else None
        target_user_id = shared_user_id or contact_user_id

        if target_user_id:
            inviter_name = session.player_names.get(user_id, "Ваш друг")
            invite_text = (
                f"{inviter_name} приглашает вас присоединиться к кооперативной игре "
                "«Столицы мира». Нажмите кнопку, чтобы вступить."
            )
            try:
                await context.bot.send_message(
                    target_user_id,
                    invite_text,
                    reply_markup=coop_join_kb(session_id),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to deliver coop invite: %s", e)
                await message.reply_text(
                    "Не удалось отправить приглашение. Отправьте ссылку вручную.",
                )
            else:
                await message.reply_text(
                    "Приглашение отправлено. Как только второй игрок присоединится, продолжим настройку матча.",
                )
            return

        if (user_shared and not shared_user_id) or (contact and not contact_user_id):
            await message.reply_text(
                "У этого контакта нет Telegram-аккаунта. Передайте ссылку вручную.",
            )
            return

        text = (message.text or "").strip()
        if text and text.casefold() == "создать ссылку".casefold():
            bot_username = getattr(context.bot, "username", None)
            if not bot_username:
                get_me = getattr(context.bot, "get_me", None)
                if get_me:
                    try:
                        me = await get_me()
                        bot_username = getattr(me, "username", None)
                    except (TelegramError, HTTPError) as e:
                        logger.warning("Failed to fetch bot username for coop link: %s", e)
            if not bot_username:
                await message.reply_text(
                    "Не удалось получить имя бота. Попробуйте позже.",
                )
                return
            invite_link = f"https://t.me/{bot_username}?start=coop_{session_id}"
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🙋 Присоединиться", url=invite_link)]]
            )
            await message.reply_text(
                f"Поделитесь этой ссылкой с другом:\n{invite_link}",
                reply_markup=markup,
            )
            return


async def cb_coop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle cooperative mode callback queries."""

    q = update.callback_query
    parts = q.data.split(":")
    sessions = _get_sessions(context)

    def get_session(session_id: str) -> CoopSession | None:
        session = sessions.get(session_id)
        if session:
            return session
        session = _find_session_global(context, session_id)
        if session:
            sessions[session_id] = session
        return session

    if len(parts) >= 2 and parts[1] == "cont":
        session_id = parts[2]
        continent = parts[3]
        session = get_session(session_id)
        if not session:
            await q.answer()
            return
        if update.effective_user.id not in session.players:
            await q.answer("Не ваша кнопка", show_alert=True)
            return
        if session.continent_filter is not None:
            await q.answer("Континент уже выбран", show_alert=True)
            try:
                await q.edit_message_reply_markup(None)
            except Exception:
                pass
            return
        session.continent_filter = None if continent == "Весь мир" else continent
        session.continent_label = continent
        await q.answer()
        try:
            await q.edit_message_reply_markup(None)
        except Exception:
            pass
        for pid in session.players:
            chat_id = session.player_chats.get(pid)
            if not chat_id:
                continue
            try:
                await context.bot.send_message(
                    chat_id,
                    "Континент выбран. Выберите сложность соперника.",
                    reply_markup=coop_difficulty_kb(session_id, pid),
                )
            except (TelegramError, HTTPError) as e:
                logger.warning("Failed to send difficulty selection: %s", e)
        return

    if len(parts) == 2:
        # coop:<continent> (admin quick start)
        continent = parts[1]
        await q.answer()
        context.user_data["continent"] = continent
        continent_filter = None if continent == "Весь мир" else continent
        if context.user_data.pop("coop_admin", False):
            # For admin quick start run test command
            await cmd_coop_test(
                update,
                context,
                user=q.from_user,
                chat=q.message.chat,
            )
        else:
            await cmd_coop_capitals(update, context)
            _, session = _find_user_session_global(context, update.effective_user.id)
            if session:
                session.continent_filter = continent_filter
                session.continent_label = continent
        return

    action = parts[1]

    if action == "test":
        if update.effective_user.id == ADMIN_ID:
            await q.answer()
            await cmd_coop_test(update, context)
        else:
            await q.answer()
        return

    if action == "diff":
        session_id = parts[2]
        player_id = int(parts[3])
        difficulty = parts[4]
        session = get_session(session_id)
        if not session:
            await q.answer()
            return
        if update.effective_user.id not in session.players or player_id != update.effective_user.id:
            await q.answer("Не ваша кнопка", show_alert=True)
            return
        if session.difficulty:
            await q.answer("Сложность уже выбрана", show_alert=True)
            try:
                await q.edit_message_reply_markup(None)
            except Exception:
                pass
            return
        session.difficulty = difficulty
        await q.answer()
        try:
            await q.edit_message_reply_markup(None)
        except Exception:
            pass
        await _start_game(context, session)
        return

    if action == "more_fact":
        session_id = parts[2]
        session = get_session(session_id)
        if not session:
            await q.answer()
            return
        pid = update.effective_user.id
        if pid not in session.players:
            await q.answer("Не ваша кнопка", show_alert=True)
            return
        msg_id = session.fact_message_ids.get(pid)
        if msg_id != q.message.message_id:
            await q.answer()
            return
        await q.answer()
        extra = await generate_llm_fact(
            session.fact_subject or "", session.fact_text or ""
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
        session.fact_message_ids.pop(pid, None)
        return

    if action != "ans":
        await q.answer()
        return

    # coop:ans:<sid>:<pid>:<idx>
    session_id = parts[2]
    player_id = int(parts[3])
    idx = int(parts[4])
    session = get_session(session_id)
    if not session or not session.current_pair:
        await q.answer()
        return
    if player_id != update.effective_user.id:
        await q.answer("Не ваша кнопка", show_alert=True)
        return
    if player_id != session.players[session.turn_index]:
        await q.answer("Сейчас не ваш ход", show_alert=True)
        return

    option = session.current_pair["options"][idx]
    correct = option == session.current_pair["correct"]
    await q.answer()
    try:
        await q.edit_message_reply_markup(None)
    except Exception:
        pass

    name = session.player_names.get(player_id, str(player_id))
    if correct:
        projected = sum(session.player_stats.values()) + session.bot_stats + 1
        await _broadcast_correct_answer(context, session, name, projected)
    else:
        text = f"{name} отвечает неверно ({option})."
        for pid in session.players:
            chat_id = session.player_chats.get(pid)
            if chat_id:
                try:
                    await context.bot.send_message(chat_id, text, parse_mode="HTML")
                except (TelegramError, HTTPError) as e:
                    logger.warning("Failed to send answer summary: %s", e)

    await _next_turn(context, session, correct)


# Module exports

__all__ = [
    "cmd_coop_capitals",
    "cmd_coop_join",
    "cmd_coop_cancel",
    "cmd_coop_test",
    "msg_coop",
    "cb_coop",
]

