import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock


# Ensure the application can import by providing a dummy token
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import app  # noqa: E402
import bot.handlers_test as ht  # noqa: E402

from bot.state import TestSession, get_user_stats

# ``handlers_test`` may have failed to import DATA if ``app`` was not available
# earlier.  Ensure the global is populated for the test run.
if ht.DATA is None:  # pragma: no cover - defensive
    ht.DATA = app.DATA

cb_test = ht.cb_test


class DummyBot:
    """Minimal bot stub collecting sent messages."""

    def __init__(self):
        self.sent: list[tuple[int, str | None, object | None]] = []
        self._mid = 0

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.sent.append((chat_id, text, reply_markup))
        self._mid += 1
        return SimpleNamespace(message_id=self._mid, text=text, caption=None, photo=None)

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        self.sent.append((chat_id, caption, reply_markup))
        self._mid += 1
        return SimpleNamespace(
            message_id=self._mid, caption=caption, text=None, photo=[object()]
        )


def test_full_test_flow(monkeypatch):
    async def run():
        # avoid real delays during the flow
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        bot = DummyBot()
        context = SimpleNamespace(bot=bot, user_data={})

        # --- start session with random countries ---
        q_start = SimpleNamespace(
            data="test:random30",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            message=SimpleNamespace(chat_id=123),
        )
        update = SimpleNamespace(
            callback_query=q_start,
            effective_chat=SimpleNamespace(id=123),
            effective_user=SimpleNamespace(id=1),
        )
        await cb_test(update, context)

        session = context.user_data["test_session"]
        assert session.total_questions == len(session.queue) + 1

        # buttons should carry the test prefix
        markup = q_start.edit_message_text.await_args.kwargs["reply_markup"]
        assert all(
            btn.callback_data.startswith("test:")
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data
        )

        # --- reveal answer ---
        q_show = SimpleNamespace(
            data="test:show",
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=q_start.message,
        )
        update.callback_query = q_show
        await cb_test(update, context)
        q_show.edit_message_reply_markup.assert_awaited()
        assert session.unknown_set
        assert get_user_stats(context.user_data).to_repeat

        # after "Показать ответ" следующий вопрос отправляется автоматически
        current = context.user_data["test_session"].current
        idx = current["options"].index(current["answer"])
        q_ans = SimpleNamespace(
            data=f"test:opt:{idx}",
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(chat_id=123),
        )
        update.callback_query = q_ans
        await cb_test(update, context)
        assert context.user_data["test_session"].stats["correct"] >= 1
        caption = bot.sent[-2][1]
        expected = (
            "✅ Верно. (Правильных ответов: "
            f"{session.stats['correct']} из {session.total_questions}. "
            f"Осталось вопросов {len(session.queue) + 1})"
        )
        assert caption.split("\n\n", 1)[0] == expected

        # --- finish session ---
        q_finish = SimpleNamespace(
            data="test:finish",
            answer=AsyncMock(),
            message=SimpleNamespace(chat_id=123),
        )
        update.callback_query = q_finish
        await cb_test(update, context)
        assert "test_session" not in context.user_data
        assert bot.sent, "No final message sent"
        final = bot.sent[-1][1]
        assert final.startswith(
            f"{session.stats['correct']} правильных из {session.total_questions}"
        )

    asyncio.run(run())


def test_show_answer_marks_unknown(monkeypatch):
    async def run():
        session = TestSession(user_id=1, queue=[])
        session.current = {
            "country": "Канада",
            "capital": "Оттава",
            "type": "country_to_capital",
            "prompt": "Канада?",
            "answer": "Оттава",
        }
        bot = DummyBot()
        context = SimpleNamespace(user_data={"test_session": session}, bot=bot)
        q = SimpleNamespace(
            data="test:show",
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(chat_id=1),
        )
        update = SimpleNamespace(callback_query=q, effective_chat=SimpleNamespace(id=1))
        monkeypatch.setattr(ht, "_next_question", AsyncMock())
        await cb_test(update, context)
        assert "Канада" in session.unknown_set
        assert "Канада" in get_user_stats(context.user_data).to_repeat
        q.edit_message_reply_markup.assert_awaited()
        ht._next_question.assert_awaited_once()
    asyncio.run(run())


def test_skip_marks_unknown(monkeypatch):
    async def run():
        session = TestSession(user_id=1, queue=[])
        session.current = {
            "country": "Канада",
            "capital": "Оттава",
            "type": "country_to_capital",
            "prompt": "Канада?",
            "answer": "Оттава",
            "options": [],
        }
        context = SimpleNamespace(user_data={"test_session": session})
        q = SimpleNamespace(data="test:skip", answer=AsyncMock(), message=SimpleNamespace(chat_id=1))
        update = SimpleNamespace(callback_query=q, effective_chat=SimpleNamespace(id=1))
        monkeypatch.setattr(ht, "_next_question", AsyncMock())
        await cb_test(update, context)
        assert "Канада" in session.unknown_set
        assert "Канада" in get_user_stats(context.user_data).to_repeat
        ht._next_question.assert_awaited_once()
    asyncio.run(run())


def test_more_fact(monkeypatch):
    async def run():
        session = TestSession(user_id=1, queue=[])
        session.current = {}
        session.fact_message_id = 1
        session.fact_subject = "Канада"
        session.fact_text = "old"
        context = SimpleNamespace(user_data={"test_session": session})
        message = SimpleNamespace(
            message_id=1,
            caption="Интересный факт: old\n\nНажми кнопку ниже, чтобы узнать еще один факт",
            text=None,
            photo=[object()],
        )
        q = SimpleNamespace(
            data="test:more_fact",
            message=message,
            answer=AsyncMock(),
            edit_message_caption=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=q)
        monkeypatch.setattr(ht, "generate_llm_fact", AsyncMock(return_value="new"))
        await cb_test(update, context)
        q.edit_message_caption.assert_awaited_once_with(
            caption="Интересный факт: old\n\nЕще один факт: new", reply_markup=None
        )
        assert session.fact_message_id is None
    asyncio.run(run())

