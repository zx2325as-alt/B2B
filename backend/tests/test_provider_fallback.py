"""P4 供应商兜底：主供应商连接/超时/限流/5xx 失败时，自动切到 config.fallback_provider 重试一次。
依赖 config.yaml: fallback_provider=deepseek 且 deepseek 在 providers 中。"""
import asyncio

import httpx
import openai
import app.harness.orchestrator as orch_mod
from app.harness.orchestrator import orchestrator


class _FailingCompletions:
    async def create(self, **kw):
        raise openai.APIConnectionError(message="boom", request=httpx.Request("POST", "http://primary"))


class _PrimaryClient:
    def __init__(self):
        self.chat = type("C", (), {"completions": _FailingCompletions()})()


_SENTINEL = object()


class _FbCompletions:
    async def create(self, **kw):
        assert kw.get("model"), "兜底应解析出该 provider 的模型"
        return _SENTINEL


class _FbClient:
    def __init__(self):
        self.chat = type("C", (), {"completions": _FbCompletions()})()


def test_create_completion_falls_back(monkeypatch):
    monkeypatch.setattr(orch_mod, "get_openai_client", lambda name: _FbClient())
    res = asyncio.run(orchestrator._create_completion(
        "multi_perspective_analysis",
        _PrimaryClient(),
        {"model": "claude-opus-4-8", "messages": [], "max_tokens": 10, "temperature": 0.5},
        "n1n",
    ))
    assert res is _SENTINEL   # 主失败 → 兜底成功


def test_resolve_model_for_fallback_provider():
    # deepseek 的 complex 档模型应能解析出来
    m = orchestrator._resolve_model_for_provider("multi_perspective_analysis", "deepseek")
    assert m and "deepseek" in m
    assert orchestrator._resolve_model_for_provider("x", "不存在的provider") is None
