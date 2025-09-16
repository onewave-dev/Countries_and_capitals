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
    application = SimpleNamespace(chat_data={1: {}, 2: {}})
    context = SimpleNamespace(
        bot=bot,
        args=[],
        user_data={},
        chat_data=application.chat_data[1],
        application=application,
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_user=SimpleNamespace(id=1))
    asyncio.run(hm.cmd_start(update, context))
    markup = bot.sent[0][2]
    buttons = [btn.text for row in markup.inline_keyboard for btn in row]
    assert any("[адм.]" in b for b in buttons)

    bot.sent.clear()
    update2 = SimpleNamespace(effective_chat=SimpleNamespace(id=2), effective_user=SimpleNamespace(id=2))
    context.chat_data = application.chat_data[2]
    asyncio.run(hm.cmd_start(update2, context))
    markup2 = bot.sent[0][2]
    buttons2 = [btn.text for row in markup2.inline_keyboard for btn in row]
    assert not any("[адм.]" in b for b in buttons2)


def test_coop_flow_steps(monkeypatch):
    import importlib
    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))
    monkeypatch.setenv("ADMIN_ID", "99")
    hco.ADMIN_ID = 99

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text, reply_markup))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    session = hco.CoopSession(session_id="s1")
    session.players = [1, 2]
    session.player_chats = {1: 1, 2: 2}
    chat_data_1 = {"sessions": {"s1": session}}
    chat_data_2 = {"sessions": {"s1": session}}
    context = SimpleNamespace(
        bot=bot,
        user_data={"coop_pending": {"session_id": "s1", "stage": "name"}},
        chat_data=chat_data_2,
        application=SimpleNamespace(chat_data={1: chat_data_1, 2: chat_data_2}),
    )

    async def reply_text(text, reply_markup=None):
        bot.sent.append((2, text, reply_markup))
        return SimpleNamespace(message_id=len(bot.sent))

    update_name = SimpleNamespace(
        effective_user=SimpleNamespace(id=2),
        message=SimpleNamespace(text="B", reply_text=reply_text),
    )
    asyncio.run(hco.msg_coop(update_name, context))
    # both players receive continent keyboard
    assert any(
        "coop:cont:s1:" in btn.callback_data
        for row in bot.sent[-1][2].inline_keyboard
        for btn in row
    )

    cq_cont = SimpleNamespace(
        data="coop:cont:s1:Азия",
        message=SimpleNamespace(chat=SimpleNamespace(id=2)),
    )

    async def answer(*args, **kwargs):
        pass

    cq_cont.answer = answer
    calls = []

    async def fake_start_game(ctx, sess):
        calls.append(sess.session_id)

    monkeypatch.setattr(hco, "_start_game", fake_start_game)
    update_cont = SimpleNamespace(callback_query=cq_cont, effective_user=SimpleNamespace(id=2))
    asyncio.run(hco.cb_coop(update_cont, context))
    assert session.continent_filter == "Азия"
    assert calls == []
    # difficulty keyboard sent
    assert any(
        "coop:diff:s1:" in btn.callback_data
        for row in bot.sent[-1][2].inline_keyboard
        for btn in row
    )

    cq_diff = SimpleNamespace(
        data="coop:diff:s1:2:easy",
        message=SimpleNamespace(chat=SimpleNamespace(id=2)),
    )
    cq_diff.answer = answer
    update_diff = SimpleNamespace(callback_query=cq_diff, effective_user=SimpleNamespace(id=2))
    asyncio.run(hco.cb_coop(update_diff, context))
    assert calls == ["s1"]


def test_cmd_coop_test_spawns_dummy_partner(monkeypatch):
    import importlib

    monkeypatch.setenv("ADMIN_ID", "5")
    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))
    hco.ADMIN_ID = 5
    hco.DUMMY_ACCURACY = 1.0

    monkeypatch.setattr(hco.DATA, "countries", lambda continent: ["France"])

    def fake_make_card_question(data, item, mode, continent):
        return {
            "prompt": "Q?",
            "options": ["A", "B", "C", "D"],
            "correct": "A",
            "country": "France",
            "capital": "A",
            "type": "country_to_capital",
        }

    monkeypatch.setattr(hco, "make_card_question", fake_make_card_question)

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text, reply_markup))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    chat_data = {}
    context = SimpleNamespace(
        bot=bot,
        user_data={"continent": "Азия"},
        chat_data=chat_data,
        application=SimpleNamespace(chat_data={77: chat_data}),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=5, full_name="Админ"),
        effective_chat=SimpleNamespace(id=77, type="private"),
        message=SimpleNamespace(text="/coop_test"),
    )

    asyncio.run(hco.cmd_coop_test(update, context))
    sessions = context.chat_data.get("sessions", {})
    assert len(sessions) == 1
    session = next(iter(sessions.values()))
    assert session.players == [5, hco.DUMMY_PLAYER_ID]
    assert session.player_chats == {5: 77}
    assert session.player_names[5] == "Админ"
    assert session.player_names[hco.DUMMY_PLAYER_ID] == "Бот-помощник"
    assert session.continent_filter == "Азия"
    assert "coop_pending" not in context.user_data

    # Question sent immediately to the human player
    assert bot.sent[0][0] == 77
    assert "Ход" in bot.sent[0][1]

    # Simulate a wrong human answer -> dummy should answer automatically and finish the game
    asyncio.run(hco._next_turn(context, session, False))
    # Dummy summary is the penultimate message; final results come last
    assert len(bot.sent) >= 3
    assert "Бот-помощник отвечает верно" in bot.sent[-2][1]
    assert bot.sent[-2][0] == 77
    assert all(chat_id is not None for chat_id, *_ in bot.sent)
    assert session.player_stats[hco.DUMMY_PLAYER_ID] >= 1


def test_bot_accuracy(monkeypatch):
    monkeypatch.setenv("ADMIN_ID", "1")
    import importlib
    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))
    hco.ADMIN_ID = 1
    hco.DUMMY_ACCURACY = 0.0

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    chat_data = {}
    context = SimpleNamespace(
        bot=bot,
        user_data={},
        chat_data=chat_data,
        application=SimpleNamespace(chat_data={1: chat_data}),
    )
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
    session = next(iter(context.chat_data["sessions"].values()))

    # Player answers wrong so that the bot takes a turn
    asyncio.run(hco._next_turn(context, session, False))
    assert session.bot_stats == 1
