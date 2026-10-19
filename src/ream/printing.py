"""
Printing: sending PDFs to a printer through CUPS - the system's own `lp`
and `lpstat` on macOS (and most Unixes).

| function          | does |
| ----------------- | ---- |
| printers()        | the printers that take jobs |
| default()         | the system's default printer, or None |
| send(path, ...)   | print a PDF; returns the job's id |
| draft_options(p)  | the options for a fast, light, black-only print on printer p |
| pending(job)      | True while the job is still queued or printing |

A draft asks for it twice over: in the standard way (IPP `print-quality`
draft, `print-color-mode` monochrome) and in the printer driver's own words,
read from its PPD - the choice called "Draft", grayscale or black ink, the
lowest resolution (Epson's drivers, for one, ignore the standard names).
Options a printer does not know are left alone by it.

Every command goes through `RUN` (subprocess.run).  The tests put a fake
there, so nothing is ever printed by them.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

RUN = subprocess.run
PPD_DIR = "/etc/cups/ppd"
MEDIA = {"a4": "A4", "letter": "Letter", "a3": "A3", "tabloid": "Tabloid"}


class PrintError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("lp") is not None and shutil.which("lpstat") is not None


def _run(command: list[str]) -> str:
    try:
        result = RUN(command, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrintError(str(exc)) from exc
    if result.returncode != 0:
        raise PrintError((result.stderr or result.stdout or "printing failed").strip())
    return result.stdout or ""


def printers() -> list[str]:
    try:
        out = _run(["lpstat", "-a"])
    except PrintError:
        return []
    return [line.split()[0] for line in out.splitlines()
            if line.strip() and "accepting" in line and "not accepting" not in line]


def default() -> str | None:
    try:
        out = _run(["lpstat", "-d"])
    except PrintError:
        return None
    match = re.search(r"destination:\s*(\S+)", out)
    return match.group(1) if match else None


def ppd_options(printer: str) -> dict[str, tuple[str, dict[str, str]]]:
    """The driver's options from its PPD: {key: (label, {choice: text})}."""
    try:
        with open(os.path.join(PPD_DIR, f"{printer}.ppd"), encoding="latin-1") as f:
            text = f.read()
    except OSError:
        return {}
    options: dict[str, tuple[str, dict[str, str]]] = {}
    for key, label in re.findall(r"^\*OpenUI \*([^/:\s]+)(?:/([^:]*))?:", text, re.M):
        options[key] = (label.strip() or key, {})
    for key, choice, words in re.findall(r"^\*([^\s/:*]+) ([^\s/:]+)(?:/([^:]*))?:", text, re.M):
        if key in options and not key.startswith(("Default", "Order")):
            options[key][1][choice] = (words or choice).strip()
    return options


def draft_options(printer: str) -> list[str]:
    """`lp` options for a draft: fast, little ink, black only."""
    wanted = {"print-quality": "3", "print-color-mode": "monochrome"}
    options = ppd_options(printer)
    plain = lambda words: re.sub(r"[^a-z]", "", words.lower())       # noqa: E731
    for key, (label, choices) in options.items():
        named = {plain(words): choice for choice, words in choices.items()}
        if plain(label) in ("printquality", "quality", "outputmode") or key in ("cupsPrintQuality",):
            for words in ("draft", "fastdraft", "economy", "fast"):
                if words in named:
                    wanted[key] = named[words]
                    break
        elif key == "ColorModel":
            for words in ("gray", "grayscale", "greyscale", "mono", "monochrome", "black"):
                if words in named:
                    wanted[key] = named[words]
                    break
        elif any(w in plain(label) for w in ("grayscale", "greyscale", "blackinkonly")) and "on" in named:
            wanted[key] = named["on"]
        elif key == "Resolution":
            dpi = lambda c: int(re.match(r"\d+", c).group()) if re.match(r"\d+", c) else 10 ** 6  # noqa
            wanted[key] = min(choices, key=dpi)
    # some drivers (Epson's) only take a quality when set to their manual mode
    for key, (label, choices) in options.items():
        if plain(label) == "mode" and any(k in wanted for k in options if k != key):
            advanced = [c for c, words in choices.items() if plain(words) in ("advanced", "custom", "manual")]
            if advanced:
                wanted[key] = advanced[0]
    return [part for key, value in wanted.items() for part in ("-o", f"{key}={value}")]


def send(path: str, printer: str, *, media: str | None = None, sides: str | None = None,
         title: str | None = None, draft: bool = False) -> str:
    """Print `path` on `printer`.  `media` is a sheet name ("a4"), `sides`
    "two-sided-short-edge" / "two-sided-long-edge" for a duplex job (else
    one-sided), `draft` fast and light (see draft_options).  Returns the
    job id."""
    command = ["lp", "-d", printer]
    if title:
        command += ["-t", title]
    if media:
        command += ["-o", f"media={MEDIA.get(media, media)}"]
    command += ["-o", f"sides={sides or 'one-sided'}"]
    if draft:
        command += draft_options(printer)
    command.append(path)
    out = _run(command)
    match = re.search(r"request id is (\S+)", out)
    return match.group(1) if match else ""


def pending(job: str) -> bool:
    """Is the job still in the queue (or printing)?"""
    if not job:
        return False
    try:
        out = _run(["lpstat", "-o"])
    except PrintError:
        return False
    return any(line.split()[:1] == [job] for line in out.splitlines())
