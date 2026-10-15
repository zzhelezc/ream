"""
Profiles: named sets of settings to switch between.

A profile is everything about how the page looks and comes out - the page
format, type, spacing, margins, paper colour and stock, ink, the distress
settings, the export dpi, the canvas colour and theme - and nothing about
what is on it.  Profiles belong to you, not to a document: they are kept in
`profiles.json` in ream's home folder, in the order they were made, and any
document can take any of them.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def path() -> Path:
    base = os.environ.get("REAM_HOME") or os.path.expanduser("~/Library/Application Support/ream")
    return Path(base) / "profiles.json"


def load() -> dict[str, dict]:
    try:
        data = json.loads(path().read_text())
    except (OSError, ValueError):
        return {}
    found = data.get("profiles", {}) if isinstance(data, dict) else {}
    return {str(k): v for k, v in found.items() if isinstance(v, dict)}


def store(profiles: dict[str, dict]):
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".saving")
    temp.write_text(json.dumps({"profiles": profiles}, indent=1))
    os.replace(temp, target)


def next_name(profiles: dict[str, dict]) -> str:
    """profile1, profile2, ... - the first one not taken."""
    n = 1
    while f"profile{n}" in profiles:
        n += 1
    return f"profile{n}"
