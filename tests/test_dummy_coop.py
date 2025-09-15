import asyncio
from types import SimpleNamespace

def test_admin_button_visible_only_for_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_ID", "1")
    import importlib
    hm = importlib.reload(__import__("bot.handlers_menu", fromlist=["*"]))
    hm.ADMIN_ID = 1

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None):
            self.sent.append((chat_id, text, reply_markup))

    bot = DummyBot()
    context = SimpleNamespace(bot=bot, args=[], user_data={}, application=SimpleNamespace(bot_data={}))
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_user=SimpleNamespace(id=1))
    asyncio.run(hm.cmd_start(update, context))
    markup = bot.sent[0][2]
    buttons = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("[адм.]" in b for b in buttons)

    bot.sent.clear()
    update2 = SimpleNamespace(effective_chat=SimpleNamespace(id=2), effective_user=SimpleNamespace(id=2))
    asyncio.run(hm.cmd_start(update2, context))
    markup2 = bot.sent[0][2]
    buttons2 = [btn.text for row in markup2.inline_keyboard for btn in row]
    assert not any("[адм.]" in b for b in buttons2)


def test_coop_continent_selection(monkeypatch):
    monkeypatch.setenv("ADMIN_ID", "99")
    import importlib
    hm = importlib.reload(__import__("bot.handlers_menu", fromlist=["*"]))
    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))
    hm.ADMIN_ID = 99
    hco.ADMIN_ID = 99

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None):
            self.sent.append((chat_id, text, reply_markup))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    context = SimpleNamespace(bot=bot, user_data={}, application=SimpleNamespace(bot_data={}), args=[])

    class DummyCQ:
        def __init__(self):
            self.data = "menu:coop"
            self.markup = None

        async def answer(self, *args, **kwargs):
            pass

        async def edit_message_text(self, text, reply_markup=None):
            self.markup = reply_markup

    update_menu = SimpleNamespace(callback_query=DummyCQ(), effective_user=SimpleNamespace(id=1))
    asyncio.run(hm.cb_menu(update_menu, context))
    buttons = [btn.callback_data for row in update_menu.callback_query.markup.inline_keyboard for btn in row]
    assert "coop:Азия" in buttons

    cq2 = SimpleNamespace(data="coop:Азия", message=SimpleNamespace(chat=SimpleNamespace(id=100)))
    async def answer(*args, **kwargs):
        pass
    cq2.answer = answer
    update_coop = SimpleNamespace(
        callback_query=cq2,
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=100, type="private"),
        message=None,
    )
    asyncio.run(hco.cb_coop(update_coop, context))
    sessions = context.application.bot_data.get("coop_sessions")
    assert sessions, "Session not created"
    session = next(iter(sessions.values()))
    assert session.continent_filter == "Азия"
    assert context.user_data["continent"] == "Азия"


def test_bot_accuracy(monkeypatch):
    monkeypatch.setenv("ADMIN_ID", "1")
    import importlib
    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))
    hco.ADMIN_ID = 1

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    context = SimpleNamespace(bot=bot, user_data={}, application=SimpleNamespace(bot_data={}))
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=1, type="private"),
        message=SimpleNamespace(text="/coop_test"),
    )

    # deterministic question
    def fake_make_card_question(data, item, mode, continent):
        return {
            "prompt": "Q?",
            "options": ["A", "B"],
            "correct": "A",
            "country": "X",
            "capital": "A",
            "type": "country_to_capital",
        }

    monkeypatch.setattr(hco, "make_card_question", fake_make_card_question)
    monkeypatch.setattr(hco.random, "random", lambda: 0.0)

    asyncio.run(hco.cmd_coop_test(update, context))
    session = next(iter(context.application.bot_data["coop_sessions"].values()))

    # Player answers wrong so that the bot takes a turn
    asyncio.run(hco._next_turn(context, session, False))
    assert session.bot_stats == 1
