"""Dispatcher tests using fake agents."""
from __future__ import annotations

from jarvis.dispatcher import Dispatcher
from jarvis.router import Routed


class _Echo:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def execute(self, task: str) -> str:
        return f"{self.prefix}: {task}"


class _Boom:
    def execute(self, task: str) -> str:
        raise RuntimeError("boom")


def test_dispatch_to_matching_agent():
    d = Dispatcher({"code": _Echo("code")})
    out = d.execute(Routed(skill="code", task="hello"))
    assert out == "code: hello"


def test_unknown_skill_returns_string():
    d = Dispatcher({})
    out = d.execute(Routed(skill="mystery", task="x"))
    assert "mystery" in out.lower() or "handler" in out.lower()


def test_agent_exception_caught():
    d = Dispatcher({"code": _Boom()})
    out = d.execute(Routed(skill="code", task="x"))
    assert isinstance(out, str)
    assert "wrong" in out.lower()
