"""Smoke tests that don't touch audio hardware or external APIs."""
from __future__ import annotations

import importlib


def test_package_imports():
    mod = importlib.import_module("jarvis")
    assert mod.__version__


def test_coder_result_short_truncates():
    from jarvis.coder import CoderResult

    long = "Sentence one. " + ("x" * 500)
    r = CoderResult(success=True, output=long)
    assert len(r.short) <= 205
    assert r.short.startswith("Sentence one.")


def test_coder_result_failure_short():
    from jarvis.coder import CoderResult

    r = CoderResult(success=False, output="", error="boom")
    assert "failed" in r.short.lower()
    assert "boom" in r.short
