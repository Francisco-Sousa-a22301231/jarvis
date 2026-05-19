"""Example custom skill — weather lookup.

Drop this file into ~/.jarvis/skills/ to register it. Three module-level
names are required: ID, DESCRIPTION, execute(task) -> str.

This example uses the free Open-Meteo API (no key needed). Replace with
your provider of choice.
"""
from __future__ import annotations

import urllib.parse
import urllib.request


ID = "weather"
DESCRIPTION = (
    "Check current weather for a place. ex: 'what's the weather in Cascais', "
    "'weather in Lisbon today'"
)


def execute(task: str) -> str:
    place = _extract_place(task) or "Cascais"  # default to Francisco's town
    try:
        lat, lon, name = _geocode(place)
        temp_c, code = _current(lat, lon)
    except Exception as e:
        return f"Couldn't fetch weather: {e}"

    return f"{name}: {temp_c:.0f}°C, {_describe(code)}."


def _extract_place(task: str) -> str | None:
    # Naive: take everything after the last "in"
    parts = task.lower().rsplit(" in ", 1)
    if len(parts) == 2 and parts[1]:
        return parts[1].strip().rstrip("?. ").title()
    return None


def _geocode(place: str) -> tuple[float, float, str]:
    url = (
        "https://geocoding-api.open-meteo.com/v1/search?name="
        + urllib.parse.quote(place)
        + "&count=1"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        import json

        data = json.loads(r.read().decode())
    res = (data.get("results") or [None])[0]
    if not res:
        raise ValueError(f"unknown place: {place}")
    return float(res["latitude"]), float(res["longitude"]), res["name"]


def _current(lat: float, lon: float) -> tuple[float, int]:
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        "&current_weather=true"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        import json

        data = json.loads(r.read().decode())
    cw = data["current_weather"]
    return float(cw["temperature"]), int(cw["weathercode"])


def _describe(code: int) -> str:
    # WMO weather codes — short summary
    mapping = {
        0: "clear",
        1: "mostly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "foggy",
        48: "foggy",
        51: "light drizzle",
        53: "drizzle",
        55: "heavy drizzle",
        61: "light rain",
        63: "rain",
        65: "heavy rain",
        71: "light snow",
        73: "snow",
        75: "heavy snow",
        80: "rain showers",
        81: "rain showers",
        82: "violent showers",
        95: "thunderstorm",
    }
    return mapping.get(code, f"weather code {code}")
