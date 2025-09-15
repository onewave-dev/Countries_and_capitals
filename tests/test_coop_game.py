import asyncio
from types import SimpleNamespace


def _setup_session(monkeypatch, continent=None):
    import importlib
    import bot.handlers_coop as hco
    hco = importlib.reload(hco)
    monkeypatch.setattr(hco, "coop_answer_kb", lambda *args, **kwargs: None)

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    context = SimpleNamespace(
        bot=bot,
        application=SimpleNamespace(bot_data={}),
    )

    session = hco.CoopSession(session_id="s1")
    session.players = [1, 2]
    session.player_chats = {1: 1, 2: 2}
    session.player_names = {1: "A", 2: "B"}
    session.continent_filter = continent
    context.application.bot_data["coop_sessions"] = {"s1": session}
    return hco, session, context, bot


def test_question_stays_on_wrong_answer(monkeypatch):
    hco, session, context, bot = _setup_session(monkeypatch, continent="Европа")
    asyncio.run(hco._start_game(context, session))
    first = bot.sent[0][1]
    asyncio.run(hco._next_turn(context, session, False))
    second = bot.sent[2][1]
    assert first.split("\n", 1)[1] == second.split("\n", 1)[1]
    assert len(session.remaining_pairs) > 0


def test_turn_order_cycles(monkeypatch):
    hco, session, context, bot = _setup_session(monkeypatch, continent="Европа")
    asyncio.run(hco._start_game(context, session))
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 1
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 0
    chats = [bot.sent[i][0] for i in range(0, len(bot.sent), 2)]
    assert chats[:3] == [1, 2, 1]


def test_world_mode_limit(monkeypatch):
    hco, session, context, bot = _setup_session(monkeypatch, continent=None)
    monkeypatch.setattr(hco.random, "sample", lambda seq, k: list(seq)[:k])
    asyncio.run(hco._start_game(context, session))
    assert len(session.remaining_pairs) == 30
