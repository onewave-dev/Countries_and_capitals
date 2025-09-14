import asyncio
from types import SimpleNamespace

from bot.state import CardSession
from bot.handlers_cards import _finish_session
from app import DATA


class DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))
def test_finish_session_lists_unanswered():
    country = DATA.countries()[0]
    capital = DATA.capital_by_country[country]
    session = CardSession(user_id=1, queue=[], stats={"shown": 1, "known": 0})
    session.current = {
        "type": "country_to_capital",
        "country": country,
        "capital": capital,
        "prompt": "",
        "answer": capital,
        "options": [],
    }
    context = SimpleNamespace(bot=DummyBot(), user_data={"card_session": session})
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=123))

    asyncio.run(_finish_session(update, context))

    assert context.bot.sent, "No message was sent"
    message_text = context.bot.sent[0][1]
    assert "Неизвестные" in message_text
    assert country in message_text and capital in message_text


def test_finish_session_skips_answered_current():
    country = DATA.countries()[1]
    capital = DATA.capital_by_country[country]
    session = CardSession(user_id=1, queue=[], stats={"shown": 1, "known": 0})
    session.current = {
        "type": "country_to_capital",
        "country": country,
        "capital": capital,
        "prompt": "",
        "answer": capital,
        "options": [],
    }
    session.current_answered = True
    context = SimpleNamespace(bot=DummyBot(), user_data={"card_session": session})
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=123))

    asyncio.run(_finish_session(update, context))

    message_text = context.bot.sent[0][1]
    assert country not in message_text and capital not in message_text
    assert not session.unknown_set
