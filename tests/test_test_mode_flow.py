import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock


# Ensure the application can import by providing a dummy token
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot.handlers_test as ht  # noqa: E402
import app  # noqa: E402

# ``handlers_test`` may have failed to import DATA if ``app`` was not available
# earlier.  Ensure the global is populated for the test run.
if ht.DATA is None:  # pragma: no cover - defensive
    ht.DATA = app.DATA

cb_test = ht.cb_test


class DummyBot:
    """Minimal bot stub collecting sent messages."""

    def __init__(self):
        self.sent: list[tuple[int, str, object | None]] = []

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.sent.append((chat_id, text, reply_markup))


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
        assert session.stats["total"] == 1

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
            edit_message_text=AsyncMock(),
            message=q_start.message,
        )
        update.callback_query = q_show
        await cb_test(update, context)
        q_show.edit_message_text.assert_awaited()

        # --- next question and answer correctly ---
        q_next = SimpleNamespace(
            data="test:next",
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            message=q_start.message,
        )
        update.callback_query = q_next
        await cb_test(update, context)
        q_next.edit_message_text.assert_awaited()

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

    asyncio.run(run())

