import asyncio
from types import SimpleNamespace


def test_admin_button_visible_only_for_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_ID", "1")
    import bot.handlers_menu as hm
    hm.ADMIN_ID = 1

    class DummyCQ:
        def __init__(self):
            self.data = "menu:coop"
            self.markup = None

        async def answer(self, *args, **kwargs):
            pass

        async def edit_message_text(self, text, reply_markup=None):
            self.markup = reply_markup

    update = SimpleNamespace(
        callback_query=DummyCQ(), effective_user=SimpleNamespace(id=1)
    )
    context = SimpleNamespace()
    asyncio.run(hm.cb_menu(update, context))
    assert update.callback_query.markup is not None
    buttons = [
        btn.text for row in update.callback_query.markup.inline_keyboard for btn in row
    ]
    assert any("[адм.]" in b for b in buttons)

    # Non-admin should not see the button
    class Bot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None):
            self.sent.append((chat_id, text, reply_markup))

    bot = Bot()
    q = DummyCQ()
    update2 = SimpleNamespace(
        callback_query=q,
        effective_user=SimpleNamespace(id=2),
        effective_chat=SimpleNamespace(id=100, type="private"),
        message=None,
    )
    context2 = SimpleNamespace(
        bot=bot, user_data={}, application=SimpleNamespace(bot_data={})
    )
    asyncio.run(hm.cb_menu(update2, context2))
    assert q.markup is None


def test_dummy_player_cycle(monkeypatch):
    monkeypatch.setenv("ADMIN_ID", "1")
    import bot.handlers_coop as hco
    hco.ADMIN_ID = 1

    class DummyBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
            self.sent.append((chat_id, text))
            return SimpleNamespace(message_id=len(self.sent))

    class DummyQueue:
        def run_once(self, callback, delay, data=None, name=None):
            return SimpleNamespace(schedule_removal=lambda: None)

    bot = DummyBot()
    context = SimpleNamespace(
        bot=bot,
        user_data={},
        application=SimpleNamespace(bot_data={}, job_queue=DummyQueue()),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        effective_chat=SimpleNamespace(id=1, type="private"),
        message=None,
    )

    monkeypatch.setattr(hco, "get_flag_image_path", lambda c: None)

    def fake_question(data, continent, mode):
        return {
            "prompt": "Q?",
            "options": ["A", "B", "C", "D"],
            "correct": "A",
            "country": "X",
            "capital": "A",
            "type": "country_to_capital",
        }

    monkeypatch.setattr(hco, "pick_question", fake_question)
    monkeypatch.setattr(hco.random, "random", lambda: 1.0)
    monkeypatch.setattr(hco.random, "uniform", lambda a, b: a)

    asyncio.run(hco.cmd_coop_test(update, context))
    session = next(iter(context.application.bot_data["coop_sessions"].values()))

    for i in range(3):
        qdata = f"coop:ans:{session.session_id}:1:1"
        cq = SimpleNamespace(data=qdata)

        async def answer(*args, **kwargs):
            pass

        async def edit_message_reply_markup(*args, **kwargs):
            pass

        cq.answer = answer
        cq.edit_message_reply_markup = edit_message_reply_markup
        cb_update = SimpleNamespace(callback_query=cq, effective_user=SimpleNamespace(id=1))
        asyncio.run(hco.cb_coop(cb_update, context))
        bot_ctx = SimpleNamespace(
            job=SimpleNamespace(data={"session_id": session.session_id}),
            application=context.application,
            bot=bot,
        )
        asyncio.run(hco._bot_move(bot_ctx))
        session = context.application.bot_data.get("coop_sessions", {}).get(session.session_id)
        if session:
            asyncio.run(hco._start_round(context, session))

    results = [msg for _, msg in bot.sent if "Игрок 2" in msg]
    assert len(results) >= 3
    assert "Игрок 2" in results[0] and "✅" in results[0]
    assert "Игрок 2" in results[1] and "✅" in results[1]
    assert "Игрок 2" in results[2] and "❌" in results[2]
