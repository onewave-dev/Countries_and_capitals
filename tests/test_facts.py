import sys
from pathlib import Path
import types
import asyncio

import pytest

# add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

# stub langchain modules if not installed
class _ChatOpenAI:
    def __init__(self, *args, **kwargs):
        pass

    async def ainvoke(self, messages):
        raise NotImplementedError

langchain_openai_stub = types.SimpleNamespace(ChatOpenAI=_ChatOpenAI)
sys.modules.setdefault("langchain_openai", langchain_openai_stub)

module_messages = types.ModuleType("langchain_core.messages")


class _HumanMessage:
    def __init__(self, content: str) -> None:
        self.content = content


module_messages.HumanMessage = _HumanMessage
sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
sys.modules["langchain_core.messages"] = module_messages

from bot import facts
from langchain_openai import ChatOpenAI


class DummyResponse:
    def __init__(self, content: str) -> None:
        self.content = content


def test_fact_length(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    async def fake_ainvoke(self, messages):
        return DummyResponse("1. short fact\n2. " + "a" * 200 + "\n3. another short fact")

    monkeypatch.setattr(ChatOpenAI, "ainvoke", fake_ainvoke)
    facts._cache.clear()

    fact = asyncio.run(facts.get_random_fact("кот"))
    assert len(fact) <= 150
    assert all(len(f) <= 150 for f in facts._cache["кот"])


def test_cache(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    calls = 0

    async def fake_ainvoke(self, messages):
        nonlocal calls
        calls += 1
        return DummyResponse("факт один\nфакт два\nфакт три")

    monkeypatch.setattr(ChatOpenAI, "ainvoke", fake_ainvoke)
    facts._cache.clear()

    asyncio.run(facts.get_random_fact("пингвин"))
    assert calls == 1
    asyncio.run(facts.get_random_fact("пингвин"))
    assert calls == 1