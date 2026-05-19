"""Multi-project routing.

Resolves which project a coding task targets by inspecting the transcript for
project names / aliases. If no project is mentioned, the first project in the
config wins (treat it as the default).

Pattern shapes we match (case-insensitive):
  - "in <alias>"     →  "in MyLessons add a dark-mode toggle"
  - "on <alias>"     →  "on jarvis fix the brief composer"
  - "for <alias>"    →  "for the lessons project ..."
  - "<alias>:"       →  "MyLessons: refactor the auth module"
The matched span is stripped from the transcript before the router sees it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    aliases: tuple[str, ...] = field(default_factory=tuple)


def _alias_pattern(alias: str) -> re.Pattern[str]:
    a = re.escape(alias)
    return re.compile(
        rf"(?:\b(?:in|on|for)\s+(?:the\s+)?{a}\b|\b{a}\s*:\s*)",
        re.I,
    )


def resolve_project(
    transcript: str,
    projects: tuple[Project, ...],
) -> tuple[Project | None, str]:
    """Return (matched_or_default_project, cleaned_transcript).

    matched_or_default_project is:
      - the explicitly-named project, if the transcript names one;
      - else the first project in the list (default), if any;
      - else None.

    cleaned_transcript has the project mention stripped so the router /
    coder gets a clean task description.
    """
    if not projects:
        return None, transcript

    for p in projects:
        for alias in (p.name, *p.aliases):
            if not alias:
                continue
            m = _alias_pattern(alias).search(transcript)
            if m:
                cleaned = (transcript[: m.start()] + " " + transcript[m.end() :]).strip()
                # Collapse multiple spaces
                cleaned = re.sub(r"\s+", " ", cleaned)
                return p, cleaned

    return projects[0], transcript
