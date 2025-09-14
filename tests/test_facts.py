import sys
import json
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import os

# add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import bot.facts  # noqa: E402

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import app  # noqa: E402
cb_cards = app.cb_cards  # noqa: E402
from bot.state import CardSession  # noqa: E402


def test_get_static_fact_uses_random_fact(tmp_path, monkeypatch):
    data = {"Канада": ["fact1", "fact2"]}
    file = tmp_path / "facts_st.json"
    file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bot.facts, "_facts_path", file)
    bot.facts._facts = json.loads(file.read_text(encoding="utf-8"))
    monkeypatch.setattr(bot.facts.random, "choice", lambda seq: seq[1])
    fact = bot.facts.get_static_fact("Канада")
    assert fact == "Интересный факт: fact2"


def test_cards_more_fact(monkeypatch):
    async def run():
        session = CardSession(user_id=1, queue=[])
        session.current = {}
        session.fact_message_id = 1
        session.fact_subject = "Канада"
        session.fact_text = "old"
        context = SimpleNamespace(user_data={"card_session": session})

        message = SimpleNamespace(
            message_id=1,
            text="Интересный факт: old\n\nНажми кнопку ниже, чтобы узнать еще один факт",
            caption=None,
            photo=None,
        )
        q = SimpleNamespace(
            data="cards:more_fact",
            message=message,
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
            edit_message_caption=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=q)

        monkeypatch.setattr(
            "bot.handlers_cards.generate_llm_fact", AsyncMock(return_value="new")
        )

        await cb_cards(update, context)

        q.edit_message_text.assert_awaited_once_with(
            "Интересный факт: old\n\nЕще один факт: new", reply_markup=None
        )
        assert session.fact_message_id is None

    asyncio.run(run())


def test_generate_llm_fact_handles_list_content(monkeypatch):
    async def run():
        resp = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=[
                            {"type": "text", "text": "fact1"},
                            {"type": "text", "text": " fact2"},
                        ]
                    )
                )
            ]
        )
        create = AsyncMock(return_value=resp)
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        monkeypatch.setattr(bot.facts, "_client", fake_client)
        fact = await bot.facts.generate_llm_fact("Канада", "old")
        assert fact == "fact1 fact2"

    asyncio.run(run())
