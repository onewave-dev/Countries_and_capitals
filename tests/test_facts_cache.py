import sys
from pathlib import Path
import types
import asyncio
import json
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


def load_facts(monkeypatch, cache_path: Path | None = None):
    if cache_path is not None:
        monkeypatch.setenv("FACTS_CACHE_PATH", str(cache_path))
    else:
        monkeypatch.delenv("FACTS_CACHE_PATH", raising=False)
    sys.modules.pop("bot.facts", None)
    import bot.facts as facts
    return facts


def test_refresh_expired_preserve_fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    cache_file = tmp_path / "facts.json"

    now = datetime.now(timezone.utc)
    expired = now - timedelta(days=6)
    fresh = now - timedelta(days=4, hours=1)
    data = {
        "волк": {"facts": ["старый факт"], "updated_at": expired.isoformat()},
        "лисица": {"facts": ["средний факт"], "updated_at": fresh.isoformat()},
    }
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    facts = load_facts(monkeypatch, cache_file)
    calls: list[str] = []

    async def fake_fetch(subject: str) -> list[str]:
        calls.append(subject)
        return [f"новый {subject} факт1", f"новый {subject} факт2"]

    monkeypatch.setattr(facts, "_fetch_facts", fake_fetch)

    asyncio.run(facts.preload_facts(["волк", "лисица"]))

    assert calls == ["волк"]

    saved = json.loads(cache_file.read_text(encoding="utf-8"))
    assert saved["лисица"] == data["лисица"]
    assert saved["волк"]["updated_at"] != data["волк"]["updated_at"]
    assert saved["волк"]["facts"] != data["волк"]["facts"]


def test_load_cache_ignores_non_dict(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    cache_file = tmp_path / "facts.json"

    now = datetime.now(timezone.utc).isoformat()
    data = {"ok": {"facts": ["f"], "updated_at": now}, "bad": ["not", "dict"]}
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    facts = load_facts(monkeypatch, cache_file)

    assert "ok" in facts._cache
    assert "bad" not in facts._cache
