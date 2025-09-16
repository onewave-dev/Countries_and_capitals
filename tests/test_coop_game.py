import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


def _setup_session(monkeypatch, continent=None):
    import importlib
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    import app  # ensure application is initialised before importing handlers
    import bot.handlers_coop as hco
    hco = importlib.reload(hco)
    calls = []

    def fake_answer_kb(session_id, player_id, options):
        calls.append(player_id)
        return None

    monkeypatch.setattr(hco, "coop_answer_kb", fake_answer_kb)
    monkeypatch.setattr(hco, "get_flag_image_path", lambda *_: None)
    async def no_sleep(*args, **kwargs):
        pass
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    class DummyBot:
        def __init__(self):
            self.sent = []
            self.photos = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            entry = (chat_id, text, reply_markup)
            self.sent.append(entry)
            return SimpleNamespace(message_id=len(self.sent))

        async def send_photo(
            self, chat_id, photo, caption=None, reply_markup=None, parse_mode=None
        ):
            entry = (chat_id, caption, reply_markup)
            self.sent.append(entry)
            self.photos.append((chat_id, caption))
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
    return hco, session, context, bot, calls


def test_continent_prompt_after_names(monkeypatch):
    import importlib
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    import app  # ensure application is initialised before importing handlers
    hco = importlib.reload(importlib.import_module("bot.handlers_coop"))

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


def test_preselected_continent_skips_prompt(monkeypatch):
    import importlib

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    import app  # ensure application is initialised before importing handlers

    hco = importlib.reload(importlib.import_module("bot.handlers_coop"))

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
    session.continent_filter = "Европа"
    session.continent_label = "Европа"
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
    assert any("Выберите сложность" in t for t in texts)
    assert all("Выберите континент" not in t for t in texts)


def test_question_stays_on_wrong_answer(monkeypatch):
    hco, session, context, bot, calls = _setup_session(monkeypatch, continent="Европа")
    asyncio.run(hco._start_game(context, session))
    prompt = session.current_pair["prompt"]
    question_messages = [entry for entry in bot.sent if entry[1] == prompt]
    assert len(question_messages) == len(session.players)
    assert {chat_id for chat_id, *_ in question_messages} == set(session.player_chats.values())

    initial_len = len(bot.sent)
    asyncio.run(hco._next_turn(context, session, False))
    prompt_after = session.current_pair["prompt"]
    assert prompt_after == prompt
    new_messages = bot.sent[initial_len:]
    assert len(new_messages) == len(session.players)
    assert all(text == prompt for _, text, _ in new_messages)
    assert {chat_id for chat_id, *_ in new_messages} == set(session.player_chats.values())
    assert len(session.remaining_pairs) > 0
    assert calls.count(session.players[0]) == 1
    assert calls.count(session.players[1]) == 1


def test_turn_order_cycles(monkeypatch):
    hco, session, context, bot, _ = _setup_session(monkeypatch, continent="Европа")
    monkeypatch.setattr(hco.random, "random", lambda: 1.0)
    asyncio.run(hco._start_game(context, session))
    prompt = session.current_pair["prompt"]
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 1
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 0
    question_chats = [chat for chat, text, *_ in bot.sent if text == prompt]
    assert question_chats == [1, 2, 2, 1, 1, 2]


def test_second_player_answer_advances_pair_for_bot(monkeypatch):
    hco, session, context, bot, _ = _setup_session(monkeypatch, continent="Европа")
    asyncio.run(hco._start_game(context, session))
    assert len(session.remaining_pairs) >= 2

    first_prompt = session.current_pair["prompt"]
    second_prompt = session.remaining_pairs[1]["prompt"]

    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 1

    monkeypatch.setattr(hco.random, "random", lambda: 1.0)
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 0
    assert session.current_pair["prompt"] == first_prompt

    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 1
    assert session.current_pair["prompt"] == first_prompt

    monkeypatch.setattr(hco.random, "random", lambda: 0.0)
    captured_prompts: list[str] = []

    async def fake_broadcast(context_arg, session_arg, name, projected_total=None):
        captured_prompts.append(session_arg.current_pair["prompt"])

    monkeypatch.setattr(hco, "_broadcast_correct_answer", fake_broadcast)

    asyncio.run(hco._next_turn(context, session, True))

    assert captured_prompts and captured_prompts[0] == second_prompt


def test_world_mode_limit(monkeypatch):
    hco, session, context, bot, _ = _setup_session(monkeypatch, continent=None)
    monkeypatch.setattr(hco.random, "sample", lambda seq, k: list(seq)[:k])
    asyncio.run(hco._start_game(context, session))
    assert len(session.remaining_pairs) == 30


def test_score_broadcast_includes_team_total(monkeypatch):
    hco, session, context, bot, _ = _setup_session(monkeypatch, continent="Европа")
    asyncio.run(hco._start_game(context, session))
    asyncio.run(hco._next_turn(context, session, True))

    score_messages = [text for _, text, *_ in bot.sent if text and text.startswith("Текущий счёт:")]
    expected = "Текущий счёт: A и B — 1, Бот — 0"
    assert expected in score_messages
    assert not bot.photos


def test_correct_answer_sends_flag_photo(monkeypatch, tmp_path):
    hco, session, context, bot, _ = _setup_session(monkeypatch, continent="Европа")

    flag_file = tmp_path / "flag.png"
    flag_file.write_bytes(b"fake")

    monkeypatch.setattr(hco, "get_flag_image_path", lambda *_: flag_file)

    session.current_pair = {
        "country": "Франция",
        "capital": "Париж",
        "type": "country_to_capital",
        "prompt": "Столица Франции?",
        "options": ["Париж", "Марсель", "Ницца", "Лион"],
        "correct": "Париж",
    }
    session.remaining_pairs = [session.current_pair]
    session.turn_index = 0
    session.total_pairs = 1

    callback = SimpleNamespace(
        data=f"coop:ans:{session.session_id}:1:0",
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
    )
    update = SimpleNamespace(callback_query=callback, effective_user=SimpleNamespace(id=1))

    asyncio.run(hco.cb_coop(update, context))

    assert bot.photos
    assert len(bot.photos) == len(session.players)
    captions = [caption for _, caption in bot.photos]
    assert all("Франция" in caption for caption in captions)
    assert any("Столица: Париж" in caption for caption in captions)
    first_entry = next(e for e in bot.sent if e[1] and "Франция" in e[1])
    caption = first_entry[1]
    markup = first_entry[2]
    assert "Правильных ответов: 1 из 1" in caption
    assert "Интересный факт:" in caption
    assert any(
        btn.callback_data == f"coop:more_fact:{session.session_id}"
        for row in markup.inline_keyboard
        for btn in row
    )


def test_more_fact(monkeypatch):
    hco, session, context, bot, _ = _setup_session(monkeypatch, continent="Европа")

    session.current_pair = {
        "country": "Франция",
        "capital": "Париж",
        "type": "country_to_capital",
        "prompt": "?",
        "options": ["Париж"],
        "correct": "Париж",
    }
    session.remaining_pairs = [
        session.current_pair,
        {
            "prompt": "Q2",
            "options": ["A"],
            "correct": "A",
            "country": "X",
            "capital": "A",
            "type": "country_to_capital",
        },
    ]
    session.turn_index = 0
    session.total_pairs = len(session.remaining_pairs)

    monkeypatch.setattr(hco, "get_static_fact", lambda *_: "Интересный факт: old")
    monkeypatch.setattr(hco, "generate_llm_fact", AsyncMock(return_value="new"))

    callback = SimpleNamespace(
        data=f"coop:ans:{session.session_id}:1:0",
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
    )
    update = SimpleNamespace(callback_query=callback, effective_user=SimpleNamespace(id=1))
    asyncio.run(hco.cb_coop(update, context))

    msg_id = session.fact_message_ids[1]
    caption = next(e[1] for e in bot.sent if e[1] and "Франция" in e[1])

    q_more = SimpleNamespace(
        data=f"coop:more_fact:{session.session_id}",
        message=SimpleNamespace(
            chat=SimpleNamespace(id=1),
            message_id=msg_id,
            caption=caption,
            text=None,
            photo=[object()],
        ),
        answer=AsyncMock(),
        edit_message_caption=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update_more = SimpleNamespace(callback_query=q_more, effective_user=SimpleNamespace(id=1))
    asyncio.run(hco.cb_coop(update_more, context))
    q_more.edit_message_caption.assert_awaited_once()
    assert "new" in q_more.edit_message_caption.call_args[1]["caption"]
    assert 1 not in session.fact_message_ids
