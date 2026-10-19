"""
Spelling: which words on the page are not in the dictionary.

pyspellchecker's word lists (pure Python, no system libraries) in a dozen
languages, plus a personal dictionary - `dictionary.txt` in ream's home
folder, one word per line - that "add to dictionary" appends to.

English comes as US and UK.  The word list is American; UK English also
accepts British spellings by trying their American form (colour/color,
realise/realize, analyse/analyze, centre/center, defence/defense,
catalogue/catalog, travelled/traveled, programme/program), so it takes both.

What is never flagged: single letters, words with digits, ALL CAPS (acronyms),
and words with a capital inside (iPhone, McNamara) - names more often than
mistakes.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

LANGUAGES = {"en-gb": "English (UK)", "en": "English (US)", "de": "Deutsch", "fr": "Français",
             "es": "Español", "it": "Italiano", "pt": "Português", "nl": "Nederlands",
             "ru": "Русский"}
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")

# British -> American, tried in turn when a UK word is not in the list
_UK = [(re.compile(p), r) for p, r in (
    (r"our(s|ed|ing|ful|ite|ites|able|less)?$", r"or\1"),
    (r"is(e|es|ed|ing|er|ers|ation|ations)$", r"iz\1"),
    (r"ys(e|es|ed|ing)$", r"yz\1"),
    (r"tre(s|d)?$", r"ter\1"),
    (r"ence(s)?$", r"ense\1"),
    (r"ogue(s)?$", r"og\1"),
    (r"([aeiou])ll(ed|ing|er|ers)$", r"\1l\2"),
    (r"mme(s)?$", r"m\1"),
    (r"ae", r"e"),
    (r"oe", r"e"),
)]


def home() -> Path:
    base = os.environ.get("REAM_HOME") or os.path.expanduser("~/Library/Application Support/ream")
    return Path(base)


class Speller:
    def __init__(self, language: str = "en-gb"):
        from spellchecker import SpellChecker
        self.language = language if language in LANGUAGES else "en-gb"
        base = "en" if self.language.startswith("en") else self.language
        self.checker = SpellChecker(language=base, distance=2)
        self.ignored: set[str] = set()
        self.cache: dict[str, bool] = {}
        self.personal = home() / "dictionary.txt"
        try:
            words = [w.strip() for w in self.personal.read_text().splitlines() if w.strip()]
        except OSError:
            words = []
        if words:
            self.checker.word_frequency.load_words([w.lower() for w in words])

    # -- checking ----------------------------------------------------------------
    @staticmethod
    def skip(word: str) -> bool:
        core = word.strip("'’")
        return (len(core) < 2 or core.isupper() or any(c.isdigit() for c in core)
                or any(c.isupper() for c in core[1:]))

    def known(self, word: str) -> bool:
        if self.skip(word):
            return True
        key = word.strip("'’").replace("’", "'").lower()
        if key in self.cache:
            return self.cache[key]
        ok = key in self.ignored or bool(self.checker.known([key]))
        if not ok and "'" in key:                 # it's, don't, the cat's
            stem = key.split("'")[0]
            ok = bool(self.checker.known([stem])) or key in self.checker
        if not ok and self.language == "en-gb":
            ok = any(bool(self.checker.known([pattern.sub(repl, key)]))
                     for pattern, repl in _UK if pattern.search(key))
        self.cache[key] = ok
        return ok

    def misspelled(self, text: str) -> list[tuple[int, int, str]]:
        """(start, end, word) of each word in `text` the dictionary lacks."""
        return [(m.start(), m.end(), m.group()) for m in WORD.finditer(text)
                if not self.known(m.group())]

    def suggestions(self, word: str, count: int = 6) -> list[str]:
        """Likeliest first, in the word's own capitalisation."""
        key = word.lower()
        found = self.checker.candidates(key) or set()
        ranked = sorted(found, key=lambda w: -self.checker.word_frequency[w])[:count]

        def shaped(w: str) -> str:
            if word.isupper():
                return w.upper()
            if word[:1].isupper():
                return w[:1].upper() + w[1:]
            return w
        return [shaped(w) for w in ranked if w != key]

    # -- teaching it ---------------------------------------------------------------
    def add(self, word: str):
        """Into the personal dictionary, for good."""
        word = word.strip("'’")
        self.checker.word_frequency.load_words([word.lower()])
        self.cache.pop(word.lower(), None)
        self.personal.parent.mkdir(parents=True, exist_ok=True)
        with self.personal.open("a", encoding="utf-8") as handle:
            handle.write(word + "\n")

    def ignore(self, word: str):
        """For this session only."""
        key = word.strip("'’").lower()
        self.ignored.add(key)
        self.cache[key] = True
