import asyncio
from types import SimpleNamespace

from bot.handlers_coop import cmd_coop_capitals, cmd_coop_cancel


class DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))


def test_coop_capitals_from_callback_and_cancel():
    chat_data = {}
    context = SimpleNamespace(
        bot=DummyBot(),
        user_data={},
        chat_data=chat_data,
        application=SimpleNamespace(chat_data={100: chat_data}),
    )

    update_cb = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=100, type="private"),
        message=None,
    )

    asyncio.run(cmd_coop_capitals(update_cb, context))

    sessions = context.chat_data.get("sessions")
    assert sessions, "Session was not created"
    session = next(iter(sessions.values()))
    assert session.players == [1], "Wrong user registered"

    cancel_update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=100),
        message=SimpleNamespace(),
    )

    asyncio.run(cmd_coop_cancel(cancel_update, context))

    assert not context.chat_data.get("sessions"), "Session was not cancelled"
    assert any(text == "Матч отменён" for _, text in context.bot.sent)

