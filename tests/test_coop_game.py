import asyncio
from types import SimpleNamespace


def _setup_session(monkeypatch, continent=None):
    import importlib
    import bot.handlers_coop as hco
    hco = importlib.reload(hco)
    monkeypatch.setattr(hco, "coop_answer_kb", lambda *args, **kwargs: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    async def no_sleep(*args, **kwargs):
        pass
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    session = hco.CoopSession(session_id="s1")
    session.players = [1, 2]
    session.player_chats = {1: 1, 2: 2}
    session.player_names = {1: "A", 2: "B"}
    session.continent_filter = continent
    chat_data_1 = {"sessions": {"s1": session}}
    chat_data_2 = {"sessions": {"s1": session}}
    context = SimpleNamespace(
        bot=bot,
        chat_data=chat_data_1,
        application=SimpleNamespace(chat_data={1: chat_data_1, 2: chat_data_2}),
    )
    return hco, session, context, bot


def test_continent_prompt_after_names(monkeypatch):
    import importlib
    hco = importlib.reload(__import__("bot.handlers_coop", fromlist=["*"]))

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

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=2),
        message=SimpleNamespace(text="B", reply_text=reply_text),
    )
    asyncio.run(hco.msg_coop(update, context))
    texts = [t for _, t, _ in bot.sent]
    assert any("Выберите континент" in t for t in texts)


def test_question_stays_on_wrong_answer(monkeypatch):
    hco, session, context, bot = _setup_session(monkeypatch, continent="Европа")
    asyncio.run(hco._start_game(context, session))
    first = bot.sent[2][1]
    asyncio.run(hco._next_turn(context, session, False))
    second = bot.sent[4][1]
    assert first.split("\n", 1)[1] == second.split("\n", 1)[1]
    assert len(session.remaining_pairs) > 0


def test_turn_order_cycles(monkeypatch):
    hco, session, context, bot = _setup_session(monkeypatch, continent="Европа")
    monkeypatch.setattr(hco.random, "random", lambda: 1.0)
    asyncio.run(hco._start_game(context, session))
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 1
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 0
    chats = [chat for chat, text in bot.sent if text.startswith("Ход") and "\n" in text]
    assert chats[:3] == [1, 2, 1]


def test_world_mode_limit(monkeypatch):
    hco, session, context, bot = _setup_session(monkeypatch, continent=None)
    monkeypatch.setattr(hco.random, "sample", lambda seq, k: list(seq)[:k])
    asyncio.run(hco._start_game(context, session))
    assert len(session.remaining_pairs) == 30


def test_score_broadcast_includes_team_total(monkeypatch):
    hco, session, context, bot = _setup_session(monkeypatch, continent="Европа")
    asyncio.run(hco._start_game(context, session))
    asyncio.run(hco._next_turn(context, session, True))

    score_messages = [text for _, text in bot.sent if text.startswith("Текущий счёт:")]
    expected = "Текущий счёт: A и B — 1, Бот — 0"
    assert expected in score_messages
