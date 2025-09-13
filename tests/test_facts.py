import sys
from pathlib import Path
import types
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

# add project root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

# stub langchain modules if not installed
class _ChatOpenAI:
    def __init__(self, *args, **kwargs):
        pass

    async def ainvoke(self, messages):  # pragma: no cover - replaced in tests
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

from langchain_openai import ChatOpenAI


class DummyResponse:
    def __init__(self, content: str) -> None:
        self.content = content


def load_facts(monkeypatch, cache_path: Path | None = None):
    if cache_path is not None:
        monkeypatch.setenv("FACTS_CACHE_PATH", str(cache_path))
    else:
        monkeypatch.delenv("FACTS_CACHE_PATH", raising=False)
    sys.modules.pop("bot.facts", None)
    import bot.facts as facts
    return facts


def test_missing_cache_path_logs_warning(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    facts = load_facts(monkeypatch, None)
    assert "FACTS_CACHE_PATH env var is not set" in caplog.text
    assert facts._cache_path is None


def test_unwritable_cache_path_logs_warning(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    path = tmp_path / "cache.json"
    monkeypatch.setenv("FACTS_CACHE_PATH", str(path))
    monkeypatch.setattr(os, "access", lambda p, m: False)
    sys.modules.pop("bot.facts", None)
    import bot.facts as facts

    assert "not writable" in caplog.text
    assert facts._cache_path is None


def test_fact_length(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    facts = load_facts(monkeypatch, tmp_path / "cache.json")

    async def fake_ainvoke(self, messages):
        return DummyResponse("1. short fact\n2. " + "a" * 200 + "\n3. another short fact")

    monkeypatch.setattr(ChatOpenAI, "ainvoke", fake_ainvoke)

    fact = asyncio.run(facts.get_random_fact("кот"))
    prefix = "Интересный факт: "
    assert fact.startswith(prefix)
    assert len(fact) <= 150 + len(prefix)
    assert all(len(f) <= 150 for f in facts._cache["кот"]["facts"])


def test_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    facts = load_facts(monkeypatch, tmp_path / "cache.json")
    calls = 0

    async def fake_ainvoke(self, messages):
        nonlocal calls
        calls += 1
        return DummyResponse("факт один\nфакт два\nфакт три")

    monkeypatch.setattr(ChatOpenAI, "ainvoke", fake_ainvoke)

    asyncio.run(facts.get_random_fact("пингвин"))
    assert calls == 1
    asyncio.run(facts.get_random_fact("пингвин"))
    assert calls == 1


def test_cache_file_ttl(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    cache_file = tmp_path / "facts.json"
    old = datetime.now(timezone.utc) - timedelta(days=6)
    data = {"лиса": {"facts": ["старый факт"], "updated_at": old.isoformat()}}
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    calls = 0

    async def fake_ainvoke(self, messages):
        nonlocal calls
        calls += 1
        return DummyResponse("новый факт1\nновый факт2\nновый факт3")

    facts = load_facts(monkeypatch, cache_file)
    monkeypatch.setattr(ChatOpenAI, "ainvoke", fake_ainvoke)

    fact = asyncio.run(facts.get_random_fact("лиса"))
    assert calls == 1
    assert "лиса" in facts._cache
    saved = json.loads(cache_file.read_text(encoding="utf-8"))
    assert saved["лиса"]["updated_at"] != old.isoformat()
    prefix = "Интересный факт: "
    assert fact.startswith(prefix)
    assert fact[len(prefix) :] in saved["лиса"]["facts"]


def test_fallback_uses_reserve_and_schedules_refresh(monkeypatch, tmp_path):
    reserve_data = {"fox": ["fact one", "fact two"]}
    reserve_path = tmp_path / "facts_reserve.json"
    reserve_path.write_text(
        json.dumps(reserve_data, ensure_ascii=False), encoding="utf-8"
    )

    facts = load_facts(monkeypatch, tmp_path / "cache.json")
    monkeypatch.setattr(
        facts, "_reserve_facts", json.loads(reserve_path.read_text("utf-8"))
    )

    async def failing(subject: str):
        raise RuntimeError("fail")

    monkeypatch.setattr(facts, "ensure_facts", failing)

    tasks = []

    def fake_create_task(coro):
        tasks.append(coro)
        class Dummy:
            pass
        return Dummy()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    fact = asyncio.run(facts.get_random_fact("fox"))
    assert fact in {"Интересный факт: " + f + " *" for f in reserve_data["fox"]}
    assert len(tasks) == 1
    tasks[0].close()


def test_fallback_uses_country_fact(monkeypatch, tmp_path):
    reserve_data = {"Финляндия": ["страна тысячи озёр"]}
    reserve_path = tmp_path / "facts_reserve.json"
    reserve_path.write_text(
        json.dumps(reserve_data, ensure_ascii=False), encoding="utf-8"
    )

    facts = load_facts(monkeypatch, tmp_path / "cache.json")
    monkeypatch.setattr(
        facts, "_reserve_facts", json.loads(reserve_path.read_text("utf-8"))
    )

    async def failing(subject: str):
        raise RuntimeError("fail")

    monkeypatch.setattr(facts, "ensure_facts", failing)

    tasks = []

    def fake_create_task(coro):
        tasks.append(coro)
        class Dummy:
            pass
        return Dummy()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    fact = asyncio.run(
        facts.get_random_fact("Хельсинки", reserve_subject="Финляндия")
    )
    assert fact == "Интересный факт: страна тысячи озёр *"
    tasks[0].close()

