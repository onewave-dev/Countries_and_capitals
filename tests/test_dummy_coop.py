import asyncio
from types import SimpleNamespace


def test_admin_button_visible_only_for_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_ID", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
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
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))
    monkeypatch.setenv("ADMIN_ID", "99")
    hco.ADMIN_ID = 99

    class DummyBot:
        def __init__(self):
            self.sent = []
            self.photos = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text, reply_markup))
            return SimpleNamespace(message_id=len(self.sent))

        async def send_photo(
            self, chat_id, photo, caption=None, reply_markup=None, parse_mode=None
        ):
            entry = (chat_id, caption, reply_markup)
            self.sent.append(entry)
            self.photos.append(entry)
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
    async def no_sleep(*args, **kwargs):
        pass
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("ADMIN_ID", "5")
    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))
    hco.ADMIN_ID = 5
    hco.DUMMY_ACCURACY = 1.0

    monkeypatch.setattr(hco.DATA, "countries", lambda continent: ["Франция"])

    def fake_make_card_question(data, item, mode, continent):
        return {
            "prompt": "Q?",
            "options": ["A", "B", "C", "D"],
            "correct": "A",
            "country": "Франция",
            "capital": "A",
            "type": "country_to_capital",
        }

    monkeypatch.setattr(hco, "make_card_question", fake_make_card_question)

    class DummyBot:
        def __init__(self):
            self.sent = []
            self.photos = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text, reply_markup))
            return SimpleNamespace(message_id=len(self.sent))

        async def send_photo(
            self, chat_id, photo, caption=None, reply_markup=None, parse_mode=None
        ):
            entry = (chat_id, caption, reply_markup)
            self.sent.append(entry)
            self.photos.append(entry)
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

    # Question sent after the intro message to the human player
    assert bot.sent[1][0] == 77
    assert "Ход" in bot.sent[1][1]

    # Simulate a wrong human answer -> dummy should answer automatically, then the opponent bot moves
    asyncio.run(hco._next_turn(context, session, False))
    assert len(bot.sent) >= 4
    dummy_photos = [entry for entry in bot.photos if entry[1] and "Бот-помощник отвечает верно" in entry[1]]
    assert dummy_photos
    assert all(chat_id == 77 for chat_id, *_ in dummy_photos)
    opponent_photos = [entry for entry in bot.photos if entry[1] and entry[1].startswith("Бот отвечает")]
    assert opponent_photos
    assert opponent_photos[-1][0] == 77
    assert bot.sent[-1][1].startswith("Игра завершена.")
    assert all(chat_id is not None for chat_id, *_ in bot.sent)
    assert session.player_stats[hco.DUMMY_PLAYER_ID] >= 1


def test_bot_accuracy(monkeypatch):
    async def no_sleep(*args, **kwargs):
        pass
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("ADMIN_ID", "1")
    import importlib
    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))
    hco.ADMIN_ID = 1
    hco.DUMMY_ACCURACY = 0.0

    class DummyBot:
        def __init__(self):
            self.sent = []
            self.photos = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text))
            return SimpleNamespace(message_id=len(self.sent))

        async def send_photo(
            self, chat_id, photo, caption=None, reply_markup=None, parse_mode=None
        ):
            entry = (chat_id, caption)
            self.sent.append(entry)
            self.photos.append(entry)
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
    monkeypatch.setattr(hco, "get_flag_image_path", lambda *_: None)

    asyncio.run(hco.cmd_coop_test(update, context))
    session = next(iter(context.chat_data["sessions"].values()))

    # Player answers wrong so that the bot takes a turn
    asyncio.run(hco._next_turn(context, session, False))
    assert session.bot_stats == 1
    assert not bot.photos


def test_bot_takes_turn_after_second_player(monkeypatch):
    import importlib

    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))
    monkeypatch.setattr(hco, "coop_answer_kb", lambda *args, **kwargs: None)
    monkeypatch.setattr(hco, "get_flag_image_path", lambda *_: None)

    class DummyBot:
        def __init__(self):
            self.sent = []
            self.photos = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text, reply_markup, parse_mode))
            return SimpleNamespace(message_id=len(self.sent))

        async def send_photo(
            self, chat_id, photo, caption=None, reply_markup=None, parse_mode=None
        ):
            entry = (chat_id, caption, reply_markup, parse_mode)
            self.sent.append(entry)
            self.photos.append(entry)
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    session = hco.CoopSession(session_id="s1")
    session.players = [1, 2]
    session.player_chats = {1: 1, 2: 2}
    session.player_names = {1: "Игрок 1", 2: "Игрок 2"}
    session.player_stats = {1: 0, 2: 0}
    session.bot_stats = 0
    session.difficulty = "medium"
    session.remaining_pairs = [
        {
            "prompt": "Q1",
            "options": ["A1", "B1", "C1", "D1"],
            "correct": "A1",
            "country": "C1",
            "capital": "A1",
            "type": "country_to_capital",
        },
        {
            "prompt": "Q2",
            "options": ["A2", "B2", "C2", "D2"],
            "correct": "A2",
            "country": "C2",
            "capital": "A2",
            "type": "country_to_capital",
        },
        {
            "prompt": "Q3",
            "options": ["A3", "B3", "C3", "D3"],
            "correct": "A3",
            "country": "C3",
            "capital": "A3",
            "type": "country_to_capital",
        },
    ]

    chat_data_1 = {"sessions": {"s1": session}}
    chat_data_2 = {"sessions": {"s1": session}}
    context = SimpleNamespace(
        bot=bot,
        chat_data=chat_data_1,
        application=SimpleNamespace(chat_data={1: chat_data_1, 2: chat_data_2}),
    )

    async def fast_sleep(delay):
        return None

    monkeypatch.setattr(hco.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(hco.random, "random", lambda: 0.0)

    session.current_pair = None
    session.turn_index = 0

    asyncio.run(hco._ask_current_pair(context, session))
    asyncio.run(hco._next_turn(context, session, True))

    assert session.turn_index == 1
    assert session.current_pair["prompt"] == "Q2"
    assert session.player_stats == {1: 1, 2: 0}

    asyncio.run(hco._next_turn(context, session, True))

    bot_messages = [msg for msg in bot.sent if "Бот отвечает" in msg[1]]
    assert len(bot_messages) == 2
    assert all("верно" in text for _, text, *_ in bot_messages)
    assert session.bot_stats == 1
    assert not bot.photos

    question_messages = [
        (chat_id, text)
        for chat_id, text, *_ in bot.sent
        if text.startswith("Ход") and "\n" in text
    ]
    assert question_messages[-1][0] == 1
    assert "Q3" in question_messages[-1][1]

    score_messages = [text for _, text, *_ in bot.sent if text.startswith("Текущий счёт:")]
    assert "Текущий счёт: Игрок 1 и Игрок 2 — 2, Бот — 1" in score_messages

    assert session.turn_index == 0
    assert session.current_pair and session.current_pair["prompt"] == "Q3"
    assert session.player_stats == {1: 1, 2: 1}
    assert [pair["prompt"] for pair in session.remaining_pairs] == ["Q3"]
