import asyncio
from types import SimpleNamespace

from bot.handlers_quit import cmd_quit, SESSION_ENDED
from bot.state import CardSession, CoopSession


class DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def test_quit_clears_sessions_and_notifies_user():
    chat_data = {}
    context = SimpleNamespace(
        bot=DummyBot(),
        user_data={"card_session": CardSession(user_id=1)},
        chat_data=chat_data,
        application=SimpleNamespace(chat_data={100: chat_data}),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=100),
        message=SimpleNamespace(),
    )

    asyncio.run(cmd_quit(update, context))

    assert "card_session" not in context.user_data
    assert context.bot.sent == [(100, SESSION_ENDED)]


def test_quit_ends_coop_session_for_all_players():
    coop = CoopSession(session_id="abc", players=[1, 2], player_chats={1: 100, 2: 200})
    chat_data_100 = {"sessions": {"abc": coop}}
    chat_data_200 = {"sessions": {"abc": coop}}
    context = SimpleNamespace(
        bot=DummyBot(),
        user_data={},
        chat_data=chat_data_100,
        application=SimpleNamespace(chat_data={100: chat_data_100, 200: chat_data_200}),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=100),
        message=SimpleNamespace(),
    )

    asyncio.run(cmd_quit(update, context))

    assert not chat_data_100["sessions"], "Session was not removed"
    assert not chat_data_200["sessions"], "Session was not removed for partner"
    assert set(context.bot.sent) == {
        (100, SESSION_ENDED),
        (200, SESSION_ENDED),
    }

