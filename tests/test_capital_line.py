import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import app  # noqa: E402
import bot.handlers_cards as hc
import bot.handlers_sprint as hs
import bot.handlers_test as ht
import bot.handlers_coop as hco

from bot.state import CardSession, SprintSession, TestSession, CoopSession

cb_cards = hc.cb_cards
cb_sprint = hs.cb_sprint
cb_test = ht.cb_test


class DummyBot:
    """Collects sent messages for assertions."""

    def __init__(self):
        self.sent: list[tuple[int, str | None, object | None]] = []

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.sent.append((chat_id, text, reply_markup))
        return SimpleNamespace(message_id=len(self.sent), text=text)

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, parse_mode=None):
        self.sent.append((chat_id, caption, reply_markup))
        return SimpleNamespace(message_id=len(self.sent), caption=caption)


def test_cards_capital_question_includes_capital_line(monkeypatch):
    async def run():
        bot = DummyBot()
        session = CardSession(user_id=1, queue=["next"])
        session.current = {
            "country": "Канада",
            "capital": "Оттава",
            "type": "capital_to_country",
            "options": ["Канада"],
            "answer": "Канада",
        }
        context = SimpleNamespace(user_data={"card_session": session}, bot=bot)
        q = SimpleNamespace(
            data="cards:opt:0",
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(chat_id=1),
        )
        update = SimpleNamespace(callback_query=q)
        monkeypatch.setattr(hc, "get_flag_image_path", lambda c: None)
        monkeypatch.setattr(hc, "_next_card", AsyncMock())
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        await cb_cards(update, context)
        assert any("Столица: Оттава" in m[1] for m in bot.sent)

        # show answer branch
        bot.sent.clear()
        session.current = {
            "country": "Канада",
            "capital": "Оттава",
            "type": "capital_to_country",
            "answer": "Канада",
        }
        q_show = SimpleNamespace(
            data="cards:show",
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(chat_id=1),
        )
        update.callback_query = q_show
        await cb_cards(update, context)
        assert any("Столица: Оттава" in m[1] for m in bot.sent)

    asyncio.run(run())


def test_sprint_capital_question_includes_capital_line(monkeypatch):
    async def run():
        bot = DummyBot()
        session = SprintSession(user_id=1)
        session.current = {
            "country": "Канада",
            "capital": "Оттава",
            "type": "capital_to_country",
            "options": ["Канада"],
            "correct": "Канада",
        }
        context = SimpleNamespace(user_data={"sprint_session": session}, bot=bot)
        q = SimpleNamespace(
            data="sprint:opt:0",
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(chat_id=1),
        )
        update = SimpleNamespace(callback_query=q)
        monkeypatch.setattr(hs, "get_flag_image_path", lambda c: None)
        monkeypatch.setattr(hs, "_ask_question", AsyncMock())
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        await cb_sprint(update, context)
        assert any("Столица: Оттава" in m[1] for m in bot.sent)

    asyncio.run(run())


def test_test_capital_question_includes_capital_line(monkeypatch):
    async def run():
        bot = DummyBot()
        session = TestSession(user_id=1, queue=[], total_questions=1)
        session.current = {
            "country": "Канада",
            "capital": "Оттава",
            "type": "capital_to_country",
            "prompt": "Оттава?",
            "answer": "Канада",
            "options": ["Канада"],
        }
        context = SimpleNamespace(user_data={"test_session": session}, bot=bot)
        q = SimpleNamespace(
            data="test:opt:0",
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(chat_id=1),
        )
        update = SimpleNamespace(callback_query=q)
        monkeypatch.setattr(ht, "get_flag_image_path", lambda c: None)
        monkeypatch.setattr(ht, "_next_question", AsyncMock())
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        await cb_test(update, context)
        assert any("Столица: Оттава" in m[1] for m in bot.sent)

        # show answer branch
        bot.sent.clear()
        session.current = {
            "country": "Канада",
            "capital": "Оттава",
            "type": "capital_to_country",
            "prompt": "Оттава?",
            "answer": "Канада",
        }
        q_show = SimpleNamespace(
            data="test:show",
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(chat_id=1),
        )
        update.callback_query = q_show
        await cb_test(update, context)
        assert any("Столица: Оттава" in m[1] for m in bot.sent)

    asyncio.run(run())


def test_coop_bot_move_includes_capital_line(monkeypatch):
    async def run():
        bot = DummyBot()
        session = CoopSession(
            session_id="s1",
            players=[1, 2],
            player_chats={1: 1, 2: 2},
            total_rounds=2,
            current_round=1,
        )
        session.current_question = {
            "country": "Канада",
            "capital": "Оттава",
            "type": "capital_to_country",
            "prompt": "Оттава?",
            "correct": "Канада",
        }
        session.answers = {1: True, 2: False}
        session.answer_options = {1: "Канада", 2: "Бразилия"}

        class DummyQueue:
            def run_once(self, callback, delay, data=None, name=None):
                return SimpleNamespace()

        context = SimpleNamespace(
            job=SimpleNamespace(data={"session_id": "s1"}),
            application=SimpleNamespace(
                bot_data={"coop_sessions": {"s1": session}}, job_queue=DummyQueue()
            ),
            bot=bot,
        )
        monkeypatch.setattr(hco, "get_flag_image_path", lambda c: None)
        monkeypatch.setattr(hco.random, "random", lambda: 1.0)
        monkeypatch.setattr(hco.random, "uniform", lambda a, b: a)
        await hco._bot_move(context)
        assert bot.sent
        assert all("Столица: Оттава" in m[1] for m in bot.sent)

    asyncio.run(run())
