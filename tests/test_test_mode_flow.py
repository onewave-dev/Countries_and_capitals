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
msg_test_letter = ht.msg_test_letter


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

    async def edit_message_text(
        self, chat_id, message_id, text, reply_markup=None, parse_mode=None
    ):
        self.sent.append((chat_id, text, reply_markup))
        return SimpleNamespace(message_id=message_id, text=text, caption=None, photo=None)

    async def delete_message(self, chat_id, message_id):
        return True


class DummyMessage:
    def __init__(self, text: str, message_id: int):
        self.text = text
        self.message_id = message_id
        self.replies: list[str] = []

    async def reply_text(self, text: str):
        self.replies.append(text)


def test_full_test_flow(monkeypatch):
    async def run():
        # avoid real delays during the flow
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        bot = DummyBot()
        context = SimpleNamespace(bot=bot, user_data={})

        # --- configure test flow via continent and mode selection ---
        q_mode = SimpleNamespace(
            data="test:continent",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(
                return_value=SimpleNamespace(message_id=1, text=None, caption=None, photo=None)
            ),
            message=SimpleNamespace(chat_id=123, message_id=1),
        )
        update = SimpleNamespace(
            callback_query=q_mode,
            effective_chat=SimpleNamespace(id=123),
            effective_user=SimpleNamespace(id=1),
        )
        await cb_test(update, context)
        q_mode.edit_message_text.assert_awaited()

        q_select = SimpleNamespace(
            data="test:Европа",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(
                return_value=SimpleNamespace(message_id=2, text=None, caption=None, photo=None)
            ),
            message=SimpleNamespace(chat_id=123, message_id=1),
        )
        update.callback_query = q_select
        await cb_test(update, context)
        setup = context.user_data["test_setup"]
        assert setup["continent"] == "Европа"

        q_mode_all = SimpleNamespace(
            data="test:mode:all",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            message=SimpleNamespace(chat_id=123, message_id=2),
        )
        update.callback_query = q_mode_all
        await cb_test(update, context)
        subset = context.user_data["test_subset"]
        assert subset, "Preview subset should not be empty"
        preview_messages = context.user_data["test_preview_messages"]
        assert preview_messages, "Preview message ids should be stored"
        start_markup = bot.sent[-1][2]
        assert any(
            getattr(btn, "callback_data", None) == "test:start"
            for row in start_markup.inline_keyboard
            for btn in row
            if getattr(btn, "callback_data", None)
        )

        start_message_id = preview_messages[-1]
        q_start = SimpleNamespace(
            data="test:start",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            message=SimpleNamespace(chat_id=123, message_id=start_message_id),
        )
        update.callback_query = q_start
        await cb_test(update, context)

        session = context.user_data["test_session"]
        assert session.total_questions == len(session.queue) + 1

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

        fact_markup = next(
            (
                markup
                for _, _, markup in reversed(bot.sent)
                if markup
                and any(
                    getattr(btn, "callback_data", None) == "test:more_fact"
                    for row in markup.inline_keyboard
                    for btn in row
                    if getattr(btn, "callback_data", None)
                )
            ),
            None,
        )
        assert fact_markup is not None, "Fact keyboard with test prefix not found"

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


def test_letter_input_builds_preview(monkeypatch):
    async def run():
        bot = DummyBot()
        context = SimpleNamespace(
            bot=bot,
            user_data={
                "test_setup": {
                    "continent": "Европа",
                    "countries": app.DATA.countries("Европа"),
                    "mode": "subsets",
                    "subcategory": "letter",
                    "letter": None,
                },
                "test_letter_pending": True,
                "test_prompt_message_id": 7,
            },
        )

        message = DummyMessage("м", 7)
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=123),
            effective_message=message,
        )

        await msg_test_letter(update, context)

        assert context.user_data["test_subset"], "Letter subset should not be empty"
        assert context.user_data["test_letter_pending"] is False
        assert context.user_data.get("test_prompt_message_id") is None
        preview_messages = context.user_data["test_preview_messages"]
        assert preview_messages, "Preview messages should be registered"
        start_markup = bot.sent[-1][2]
        assert any(
            getattr(btn, "callback_data", None) == "test:start"
            for row in start_markup.inline_keyboard
            for btn in row
            if getattr(btn, "callback_data", None)
        )

    asyncio.run(run())


def test_letter_prompt_sent_as_separate_message(monkeypatch):
    async def run():
        bot = DummyBot()
        bot.delete_message = AsyncMock(return_value=True)
        context = SimpleNamespace(
            bot=bot,
            user_data={
                "test_setup": {
                    "continent": "Африка",
                    "countries": app.DATA.countries("Африка"),
                    "mode": "subsets",
                    "subcategory": None,
                    "letter": None,
                },
                "test_subset": [],
                "test_letter_pending": False,
                "test_prompt_message_id": 11,
            },
        )

        q = SimpleNamespace(
            data="test:sub:letter",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            message=SimpleNamespace(chat_id=123, message_id=5),
        )
        update = SimpleNamespace(
            callback_query=q,
            effective_chat=SimpleNamespace(id=123),
        )

        await cb_test(update, context)

        bot.delete_message.assert_awaited_once_with(123, 11)
        assert context.user_data["test_letter_pending"] is True
        assert context.user_data["test_prompt_message_id"] != 11
        assert bot.sent, "Letter prompt should be sent as a new message"
        chat_id, text, markup = bot.sent[-1]
        assert chat_id == 123
        assert markup is None
        assert text.startswith("📝 Тест — Африка")

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


def test_capital_question_show_and_skip_mark_country(monkeypatch):
    async def run():
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())

        def make_session() -> TestSession:
            session = TestSession(user_id=1, queue=[])
            session.current = {
                "country": "Израиль",
                "capital": "Иерусалим",
                "type": "capital_to_country",
                "prompt": "Иерусалим?",
                "answer": "Израиль",
                "options": [],
            }
            return session

        bot = DummyBot()
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=1))

        # --- show answer ---
        session = make_session()
        context = SimpleNamespace(user_data={"test_session": session}, bot=bot)
        q_show = SimpleNamespace(
            data="test:show",
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            message=SimpleNamespace(chat_id=1),
        )
        update.callback_query = q_show
        monkeypatch.setattr(ht, "_next_question", AsyncMock())
        monkeypatch.setattr(ht, "get_flag_image_path", lambda c: None)
        await cb_test(update, context)
        assert "Израиль" in session.unknown_set
        assert "Израиль" in get_user_stats(context.user_data).to_repeat
        assert any(
            "Столица: Иерусалим" in (m[1] or "") for m in bot.sent
        ), "Capital line missing in response"

        # --- skip question ---
        session = make_session()
        context.user_data = {"test_session": session}
        q_skip = SimpleNamespace(
            data="test:skip",
            answer=AsyncMock(),
            message=SimpleNamespace(chat_id=1),
        )
        update.callback_query = q_skip
        monkeypatch.setattr(ht, "_next_question", AsyncMock())
        await cb_test(update, context)
        assert "Израиль" in session.unknown_set
        assert "Израиль" in get_user_stats(context.user_data).to_repeat

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

