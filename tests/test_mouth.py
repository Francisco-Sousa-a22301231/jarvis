"""Mouth (TTS) tests. Mostly platform-fallback wiring."""
from __future__ import annotations

from unittest.mock import patch

from jarvis import mouth


def test_speak_empty_is_noop(capsys):
    m = mouth.Mouth()
    m.speak("")
    m.speak("   ")
    out = capsys.readouterr().out
    assert out == ""


def test_falls_back_to_print_when_nothing_available(capsys):
    with patch.object(mouth, "_windows_sapi_available", return_value=False), patch(
        "jarvis.mouth.shutil.which", return_value=None
    ):
        m = mouth.Mouth()
        m.speak("hello world")
    out = capsys.readouterr().out
    assert "hello world" in out


def test_uses_macos_say_when_available():
    with patch.object(mouth, "_windows_sapi_available", return_value=False), patch(
        "jarvis.mouth.shutil.which", side_effect=lambda x: "/usr/bin/say" if x == "say" else None
    ), patch("jarvis.mouth.subprocess.run") as run:
        m = mouth.Mouth()
        m.speak("hi mac")
    args = run.call_args.args[0]
    assert args[0] == "say"
    assert args[1] == "hi mac"


def test_uses_windows_sapi_when_available():
    """Windows SAPI is preferred over print when no macOS `say`."""
    fake_powershell = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"

    def which(name: str):
        return fake_powershell if name.endswith(".exe") else None

    with patch("jarvis.mouth.platform.system", return_value="Windows"), patch(
        "jarvis.mouth.shutil.which", side_effect=which
    ), patch("jarvis.mouth.subprocess.run") as run:
        run.return_value = type("P", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
        m = mouth.Mouth()
        m.speak("hi windows")
    # Verify PowerShell was invoked with the SAPI script
    call = run.call_args.args[0]
    assert call[0].endswith("powershell.exe") or call[0].endswith("pwsh.exe")
    script = call[-1]
    assert "System.Speech" in script
    assert "hi windows" in script


def test_sapi_escapes_single_quotes():
    fake_powershell = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    with patch("jarvis.mouth.shutil.which", return_value=fake_powershell), patch(
        "jarvis.mouth.subprocess.run"
    ) as run:
        run.return_value = type("P", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
        mouth._speak_windows_sapi("it's working")
    script = run.call_args.args[0][-1]
    assert "it''s working" in script  # PowerShell single-quote escape
