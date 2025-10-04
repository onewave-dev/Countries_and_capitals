import asyncio
import sys
from collections.abc import MutableMapping
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from html import escape

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
            self.edited = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            entry = (chat_id, text, reply_markup)
            self.sent.append(entry)
            return SimpleNamespace(message_id=len(self.sent), text=text)

        async def send_photo(
            self, chat_id, photo, caption=None, reply_markup=None, parse_mode=None
        ):
            entry = (chat_id, caption, reply_markup)
            self.sent.append(entry)
            self.photos.append((chat_id, caption))
            return SimpleNamespace(
                message_id=len(self.sent), caption=caption, photo=[object()]
            )

        async def edit_message_caption(
            self, chat_id, message_id, caption=None, reply_markup=None
        ):
            self.edited.append(("caption", chat_id, message_id, caption, reply_markup))

        async def edit_message_text(
            self, chat_id, message_id, text=None, reply_markup=None
        ):
            self.edited.append(("text", chat_id, message_id, text, reply_markup))

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


def _bound_async(method, instance):
    return method.__get__(instance, instance.__class__)


def _split_question_text(text):
    if not text:
        return None, text
    parts = text.split("\n\n", 1)
    if len(parts) == 2:
        header, rest = parts
        return header, rest
    return None, text


def test_join_callback_adds_player(monkeypatch):
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
    session.players = [1]
    session.player_chats = {1: 100}
    host_chat_data = {"sessions": {"s1": session}}
    join_chat_data = {}
    context = SimpleNamespace(
        bot=bot,
        user_data={},
        chat_data=join_chat_data,
        application=SimpleNamespace(chat_data={100: host_chat_data, 200: join_chat_data}),
    )

    callback = SimpleNamespace(
        data="coop:join:s1",
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=200, type="private"),
            message_id=77,
        ),
    )
    update = SimpleNamespace(
        callback_query=callback,
        effective_user=SimpleNamespace(id=2),
        effective_chat=callback.message.chat,
    )

    asyncio.run(hco.cb_coop(update, context))

    assert session.players == [1, 2]
    assert session.player_chats[2] == 200
    assert context.user_data["coop_pending"] == {"session_id": "s1", "stage": "name"}
    assert any(chat_id == 200 and "Введите ваше имя" in text for chat_id, text, _ in bot.sent)
    assert any(
        chat_id == 100 and "подключился" in (text or "") for chat_id, text, _ in bot.sent
    )


def test_start_deeplink_handles_mapping_chat_data(monkeypatch):
    import importlib

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    import app  # ensure application is initialised before importing handlers

    hco = importlib.reload(importlib.import_module("bot.handlers_coop"))
    menu = importlib.reload(importlib.import_module("bot.handlers_menu"))

    class DummyMapping(MutableMapping):
        def __init__(self, initial=None):
            self._data = dict(initial or {})

        def __getitem__(self, key):
            return self._data[key]

        def __setitem__(self, key, value):
            self._data[key] = value

        def __delitem__(self, key):
            del self._data[key]

        def __iter__(self):
            return iter(self._data)

        def __len__(self):
            return len(self._data)

        def values(self):
            return self._data.values()

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text, reply_markup))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    session = hco.CoopSession(session_id="s1")
    session.players = [1]
    session.player_chats = {1: 100}
    host_sessions = DummyMapping({"s1": session})
    host_chat_data = DummyMapping({"sessions": host_sessions})
    join_chat_data = DummyMapping()
    application_chat_data = DummyMapping({100: host_chat_data, 200: join_chat_data})

    context = SimpleNamespace(
        bot=bot,
        args=["coop_s1"],
        user_data={},
        chat_data=join_chat_data,
        application=SimpleNamespace(chat_data=application_chat_data),
    )

    chat = SimpleNamespace(id=200, type="private")

    class DummyMessage:
        def __init__(self, chat):
            self.chat = chat
            self.replies = []

        async def reply_text(self, text, reply_markup=None):
            self.replies.append((text, reply_markup))
            return SimpleNamespace(message_id=len(self.replies))

    message = DummyMessage(chat)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=2),
        effective_chat=chat,
        message=message,
    )

    asyncio.run(menu.cmd_start(update, context))

    assert session.players == [1, 2]
    assert session.player_chats[2] == 200
    assert context.user_data["coop_pending"] == {"session_id": "s1", "stage": "name"}
    assert any("Введите ваше имя" in text for text, _ in message.replies)
    assert join_chat_data["sessions"]["s1"] is session


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
    assert any("Матч начнётся" in t for t in texts)
    assert all("Выберите континент" not in t for t in texts)


def test_invite_stage_sends_contact_invitation(monkeypatch):
    import importlib

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    import app  # ensure application is initialised before importing handlers

    hco = importlib.reload(importlib.import_module("bot.handlers_coop"))

    join_calls: list[str] = []

    def fake_join_kb(session_id: str):
        join_calls.append(session_id)
        return SimpleNamespace(kind="join", session=session_id)

    monkeypatch.setattr(hco, "coop_join_kb", fake_join_kb)

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text, reply_markup))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    session = hco.CoopSession(session_id="s1")
    session.players = [1]
    session.player_names = {1: "Игрок"}
    session.player_chats = {1: 1}

    context = SimpleNamespace(
        bot=bot,
        user_data={"coop_pending": {"session_id": "s1", "stage": "invite"}},
        chat_data={"sessions": {"s1": session}},
    )

    replies: list[tuple[str, object]] = []

    async def reply_text(text, reply_markup=None):
        replies.append((text, reply_markup))
        return SimpleNamespace(message_id=len(replies))

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        message=SimpleNamespace(
            contact=SimpleNamespace(user_id=777, first_name="Друг"),
            text=None,
            reply_text=reply_text,
        ),
    )

    asyncio.run(hco.msg_coop(update, context))

    assert join_calls == ["s1"]
    assert bot.sent and bot.sent[0][0] == 777
    assert bot.sent[0][2].session == "s1"
    assert replies and "Приглашение отправлено" in replies[0][0]
    assert context.user_data["coop_pending"]["stage"] == "invite"


def test_invite_stage_sends_users_shared_invitation(monkeypatch):
    import importlib

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    import app  # ensure application is initialised before importing handlers

    hco = importlib.reload(importlib.import_module("bot.handlers_coop"))

    join_calls: list[str] = []

    def fake_join_kb(session_id: str):
        join_calls.append(session_id)
        return SimpleNamespace(kind="join", session=session_id)

    monkeypatch.setattr(hco, "coop_join_kb", fake_join_kb)

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text, reply_markup))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    session = hco.CoopSession(session_id="s1")
    session.players = [1]
    session.player_names = {1: "Игрок"}
    session.player_chats = {1: 1}

    context = SimpleNamespace(
        bot=bot,
        user_data={"coop_pending": {"session_id": "s1", "stage": "invite"}},
        chat_data={"sessions": {"s1": session}},
    )

    replies: list[tuple[str, object]] = []

    async def reply_text(text, reply_markup=None):
        replies.append((text, reply_markup))
        return SimpleNamespace(message_id=len(replies))

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        message=SimpleNamespace(
            users_shared=SimpleNamespace(
                user_ids=[888],
                users=[
                    SimpleNamespace(user_id=999),
                    SimpleNamespace(user_id=None),
                ],
            ),
            user_shared=None,
            contact=None,
            text=None,
            reply_text=reply_text,
        ),
    )

    asyncio.run(hco.msg_coop(update, context))

    assert join_calls == ["s1"]
    assert bot.sent and bot.sent[0][0] == 999
    assert bot.sent[0][2].session == "s1"
    assert replies and "Приглашение отправлено" in replies[0][0]
    assert all("нет Telegram" not in text for text, _ in replies)
    assert context.user_data["coop_pending"]["stage"] == "invite"


def test_invite_stage_handles_contact_without_user_id(monkeypatch):
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
    session.players = [1]
    session.player_names = {1: "Игрок"}
    session.player_chats = {1: 1}

    context = SimpleNamespace(
        bot=bot,
        user_data={"coop_pending": {"session_id": "s1", "stage": "invite"}},
        chat_data={"sessions": {"s1": session}},
    )

    replies: list[tuple[str, object]] = []

    async def reply_text(text, reply_markup=None):
        replies.append((text, reply_markup))
        return SimpleNamespace(message_id=len(replies))

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        message=SimpleNamespace(
            contact=SimpleNamespace(user_id=None, first_name="Друг"),
            text=None,
            reply_text=reply_text,
        ),
    )

    asyncio.run(hco.msg_coop(update, context))

    assert not bot.sent
    assert replies and "ссылку вручную" in replies[0][0]
    assert context.user_data["coop_pending"]["stage"] == "invite"


def test_invite_stage_generates_link(monkeypatch):
    import importlib

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    import app  # ensure application is initialised before importing handlers

    hco = importlib.reload(importlib.import_module("bot.handlers_coop"))

    class DummyBot:
        def __init__(self):
            self.sent = []
            self._username = None
            self._me = SimpleNamespace(username="TestBot")

        @property
        def username(self):
            return self._username

        async def get_me(self):
            return self._me

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text, reply_markup))
            return SimpleNamespace(message_id=len(self.sent))

    bot = DummyBot()
    session = hco.CoopSession(session_id="s1")
    session.players = [1]
    session.player_names = {1: "Игрок"}
    session.player_chats = {1: 1}

    context = SimpleNamespace(
        bot=bot,
        user_data={"coop_pending": {"session_id": "s1", "stage": "invite"}},
        chat_data={"sessions": {"s1": session}},
    )

    replies: list[tuple[str, object]] = []

    async def reply_text(text, reply_markup=None):
        replies.append((text, reply_markup))
        return SimpleNamespace(message_id=len(replies))

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        message=SimpleNamespace(
            contact=None,
            text="Создать ссылку",
            reply_text=reply_text,
        ),
    )

    asyncio.run(hco.msg_coop(update, context))

    expected_link = "https://t.me/TestBot?start=coop_s1"
    assert not bot.sent
    assert replies
    response_text, markup = replies[0]
    assert expected_link in response_text
    assert "Поделитесь этой ссылкой" in response_text
    assert markup is None
    assert context.user_data["coop_pending"]["stage"] == "invite"


@pytest.mark.parametrize(
    "message_payload, expected_target",
    [
        ({"user_shared": {"request_id": 1, "user_id": 555}}, 555),
        (
            {
                "users_shared": {
                    "request_id": 2,
                    "users": [{"user_id": 888, "first_name": "Друг"}],
                    "user_ids": [777],
                }
            },
            888,
        ),
    ],
)
def test_application_dispatches_shared_contact(monkeypatch, message_payload, expected_target):
    import importlib
    from telegram import Update

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    app_module = importlib.reload(importlib.import_module("app"))
    hco = importlib.import_module("bot.handlers_coop")

    join_calls: list[str] = []

    def fake_join_kb(session_id: str):
        join_calls.append(session_id)
        return SimpleNamespace(kind="join", session=session_id)

    monkeypatch.setattr(hco, "coop_join_kb", fake_join_kb)

    sent_messages: list[tuple[int, str, object]] = []

    async def fake_send_message(self, chat_id, text, reply_markup=None, parse_mode=None, **kwargs):
        sent_messages.append((chat_id, text, reply_markup))
        return SimpleNamespace(message_id=len(sent_messages))

    monkeypatch.setattr(app_module.application.bot.__class__, "send_message", fake_send_message)
    app_module.application._initialized = True
    app_module.application.bot._bot_user = SimpleNamespace(id=999)

    session = hco.CoopSession(session_id="s1")
    session.players = [1]
    session.player_names = {1: "Игрок"}
    session.player_chats = {1: 11}

    app_module.application._chat_data.clear()
    app_module.application._user_data.clear()
    app_module.application._chat_data[11]["sessions"] = {"s1": session}
    app_module.application._user_data[1] = {"coop_pending": {"session_id": "s1", "stage": "invite"}}

    message_data = {
        "message_id": 42,
        "date": int(datetime.now().timestamp()),
        "chat": {"id": 11, "type": "private"},
        "from": {"id": 1, "is_bot": False, "first_name": "Игрок"},
    }
    message_data.update(message_payload)
    update_data = {"update_id": 1000, "message": message_data}

    update = Update.de_json(update_data, app_module.application.bot)
    assert app_module.coop_message_filters.check_update(update)
    if "user_shared" in message_payload:
        assert getattr(update.message, "user_shared", None) is None
    if "users_shared" in message_payload:
        assert getattr(update.message, "users_shared", None) is not None

    asyncio.run(app_module.application.process_update(update))

    assert join_calls == ["s1"]
    assert any(chat_id == expected_target and "приглашает" in text for chat_id, text, _ in sent_messages)
    assert any(
        chat_id == 11 and "Приглашение отправлено" in text for chat_id, text, _ in sent_messages
    )
    assert app_module.application.user_data[1]["coop_pending"]["stage"] == "invite"


def test_question_stays_on_wrong_answer(monkeypatch):
    hco, session, context, bot, calls = _setup_session(monkeypatch, continent="Европа")
    asyncio.run(hco._start_game(context, session))
    prompt = session.current_pair["prompt"]
    question_messages = [entry for entry in bot.sent if _split_question_text(entry[1])[1] == prompt]
    assert len(question_messages) == len(session.players)
    assert {chat_id for chat_id, *_ in question_messages} == set(session.player_chats.values())
    assert {_split_question_text(text)[0] for _, text, _ in question_messages} == {
        "Вопрос игроку <b>A</b>:",
    }

    initial_len = len(bot.sent)
    monkeypatch.setattr(hco.random, "random", lambda: 1.0)
    asyncio.run(hco._next_turn(context, session, False))
    prompt_after = session.current_pair["prompt"]
    assert prompt_after == prompt
    new_messages = bot.sent[initial_len:]
    bot_headers = [
        _split_question_text(text)[0]
        for _, text, _ in new_messages
        if _split_question_text(text)[0] == "Вопрос игроку <b>🤖 Бот Атлас</b>:"
    ]
    assert len(bot_headers) == len(session.players)
    assert any("Ответ неверный" in (text or "") for _, text, _ in new_messages)
    human_messages = [
        entry
        for entry in new_messages
        if _split_question_text(entry[1])[0] == "Вопрос игроку <b>B</b>:"
    ]
    assert len(human_messages) == len(session.players)
    assert all(_split_question_text(text)[1] == prompt for _, text, _ in human_messages)
    assert {chat_id for chat_id, *_ in human_messages} == set(session.player_chats.values())
    assert len(session.remaining_pairs) > 0
    assert calls.count(session.players[0]) == 1
    assert calls.count(session.players[1]) == 1



def test_turn_order_cycles(monkeypatch):
    hco, session, context, bot, _ = _setup_session(monkeypatch, continent="Европа")
    monkeypatch.setattr(hco.random, "random", lambda: 1.0)
    asyncio.run(hco._start_game(context, session))
    prompt = session.current_pair["prompt"]
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 2
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 0
    question_chats = [chat for chat, text, *_ in bot.sent if _split_question_text(text)[1] == prompt]
    assert question_chats == [1, 2, 1, 2, 1, 2, 1, 2, 1, 2]



def test_second_player_answer_advances_pair_for_bot(monkeypatch):
    hco, session, context, bot, _ = _setup_session(monkeypatch, continent="Европа")
    asyncio.run(hco._start_game(context, session))
    assert len(session.remaining_pairs) >= 2

    first_prompt = session.current_pair["prompt"]
    second_prompt = session.remaining_pairs[1]["prompt"]

    monkeypatch.setattr(hco.random, "random", lambda: 1.0)
    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 2

    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 0
    assert session.current_pair["prompt"] == first_prompt

    asyncio.run(hco._next_turn(context, session, False))
    assert session.turn_index == 2
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
    hco._ensure_turn_setup(session)
    order_length = max(len(session.turn_order), 1)

    asyncio.run(hco._next_turn(context, session, True))
    interim_scores = [
        text
        for _, text, *_ in bot.sent
        if text and text.startswith("📊 <b>Текущий счёт</b>")
    ]
    assert not interim_scores, "scoreboard should not be broadcast mid-round"

    for _ in range(order_length - 1):
        asyncio.run(hco._next_turn(context, session, False))

    score_messages = [
        text
        for _, text, *_ in bot.sent
        if text and text.startswith("📊 <b>Текущий счёт</b>")
    ]
    players_total = sum(session.player_stats.values())
    expected_remaining = max(session.total_pairs - (players_total + session.bot_stats), 0)
    team_label = hco._format_team_label(session)
    assert score_messages
    scoreboard_text = score_messages[-1]
    assert (
        f"🤝 Команда {escape(team_label)} — <b>{players_total}</b>"
        in scoreboard_text
    )
    hco._ensure_turn_setup(session)
    bot_label = hco._format_bot_team_score_label(session)
    assert (
        f"🤖 {escape(bot_label)} — <b>{session.bot_stats}</b>" in scoreboard_text
    )
    remaining_line = hco._format_remaining_questions_line(expected_remaining)
    assert remaining_line in scoreboard_text
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
    assert "Правильных ответов" not in caption
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
    mock_llm = AsyncMock(return_value="new")
    monkeypatch.setattr(hco, "generate_llm_fact", mock_llm)

    callback = SimpleNamespace(
        data=f"coop:ans:{session.session_id}:1:0",
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
    )
    update = SimpleNamespace(callback_query=callback, effective_user=SimpleNamespace(id=1))
    asyncio.run(hco.cb_coop(update, context))

    target_entries = {
        key: meta
        for key, meta in session.fact_message_ids.items()
        if meta.get("country") == "Франция" and meta.get("chat_id") in {1, 2}
    }
    assert len(target_entries) == 2
    group_ids = {meta.get("group") for meta in target_entries.values()}
    assert len(group_ids) == 1
    group_id = next(iter(group_ids))
    player_messages = {
        meta["chat_id"]: (key, meta)
        for key, meta in target_entries.items()
    }
    assert set(player_messages) == {1, 2}
    msg_key, _ = player_messages[1]
    other_msg_key, _ = player_messages[2]
    msg_id = msg_key[1]
    other_msg_id = other_msg_key[1]
    caption = next(
        text for chat_id, text, _ in bot.sent if chat_id == 1 and text and "Франция" in text
    )

    q_more = SimpleNamespace(
        data=f"coop:more_fact:{session.session_id}",
        message=SimpleNamespace(
            chat=SimpleNamespace(id=1),
            message_id=msg_id,
            caption=None,
            text=caption,
            photo=[],
        ),
        answer=AsyncMock(),
    )
    update_more = SimpleNamespace(callback_query=q_more, effective_user=SimpleNamespace(id=1))
    asyncio.run(hco.cb_coop(update_more, context))

    edited_texts = [entry for entry in bot.edited if entry[0] == "text"]
    assert len(edited_texts) == 2
    for _, chat_id, mid, text, _ in edited_texts:
        assert "Еще один факт: new" in text
        assert chat_id in {1, 2}
        assert mid in {msg_id, other_msg_id}

    assert all(meta.get("country") != "Франция" for meta in session.fact_message_ids.values())
    assert group_id not in session.fact_message_groups

    q_more_second = SimpleNamespace(
        data=f"coop:more_fact:{session.session_id}",
        message=SimpleNamespace(
            chat=SimpleNamespace(id=2),
            message_id=other_msg_id,
            caption=None,
            text=caption,
            photo=[],
        ),
        answer=AsyncMock(),
    )
    update_more_second = SimpleNamespace(
        callback_query=q_more_second, effective_user=SimpleNamespace(id=2)
    )
    asyncio.run(hco.cb_coop(update_more_second, context))
    assert len([entry for entry in bot.edited if entry[0] == "text"]) == 2
    assert q_more_second.answer.await_count == 1


def test_more_fact_handles_duplicate_message_ids(monkeypatch):
    hco, session, context, bot, _ = _setup_session(monkeypatch, continent="Европа")

    session.current_pair = {
        "country": "Италия",
        "capital": "Рим",
        "type": "country_to_capital",
        "prompt": "?",
        "options": ["Рим"],
        "correct": "Рим",
    }
    session.remaining_pairs = [session.current_pair]
    session.turn_index = 0
    session.total_pairs = 1

    monkeypatch.setattr(hco, "get_static_fact", lambda *_: "Интересный факт: base")
    extra_fact = AsyncMock(return_value="extra")
    monkeypatch.setattr(hco, "generate_llm_fact", extra_fact)

    async def send_message_same(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.sent.append((chat_id, text, reply_markup))
        return SimpleNamespace(message_id=777, text=text)

    bot.send_message = _bound_async(send_message_same, bot)
    bot.edited.clear()

    callback = SimpleNamespace(
        data=f"coop:ans:{session.session_id}:1:0",
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
    )
    update = SimpleNamespace(callback_query=callback, effective_user=SimpleNamespace(id=1))

    asyncio.run(hco.cb_coop(update, context))

    assert len(session.fact_message_ids) == 2
    first_key = next(iter(session.fact_message_ids))
    metadata = session.fact_message_ids[first_key]
    message = SimpleNamespace(
        message_id=first_key[1],
        chat=SimpleNamespace(id=first_key[0]),
        caption=None,
        text=metadata.get("base_text"),
    )

    q_more = SimpleNamespace(
        data=f"coop:more_fact:{session.session_id}",
        message=message,
        answer=AsyncMock(),
    )
    update_more = SimpleNamespace(callback_query=q_more, effective_user=SimpleNamespace(id=1))

    asyncio.run(hco.cb_coop(update_more, context))

    edited_entries = [entry for entry in bot.edited if entry[0] == "text"]
    assert len(edited_entries) == 2
    assert {chat_id for _, chat_id, *_ in edited_entries} == set(session.player_chats.values())
    assert {msg_id for _, _, msg_id, *_ in edited_entries} == {first_key[1]}
    for entry in edited_entries:
        assert "Еще один факт: extra" in entry[3]

    assert not session.fact_message_ids
    assert not session.fact_message_groups
    assert q_more.answer.await_count == 1
    assert extra_fact.await_count == 1
