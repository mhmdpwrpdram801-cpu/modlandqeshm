"""Loading and merging of the spoken-form dictionaries.

Two built-in files ship with the app — the programmer glossary and the spoken
punctuation table — and the user gets a third one they own, under their profile
directory.  The user's entries are loaded last and win, which is what makes
"add my own words" a supported operation rather than a patch to the source.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .normalize import normalize, strip_zwnj

# How a replacement sits between its neighbours.
#   left  — glued to the word before it, space after   (".", "،", ")")
#   right — space before it, glued to the word after   ("(", "#")
#   both  — glued on both sides                        ("_", "/", "\n")
#   none  — spaced on both sides                       ("=", "+")
#   word  — an ordinary word
ATTACH_KINDS = frozenset({"left", "right", "both", "none", "word"})

_SPACE_AFTER = frozenset({"left", "none", "word"})
_SPACE_BEFORE = frozenset({"right", "none", "word"})


@dataclass(frozen=True)
class Entry:
    """One thing the pipeline can emit in place of a run of spoken words."""

    text: str
    attach: str = "word"
    source: str = "builtin"

    def __post_init__(self) -> None:
        if self.attach not in ATTACH_KINDS:
            raise ValueError(f"unknown attach kind: {self.attach!r}")

    @property
    def space_after(self) -> bool:
        return self.attach in _SPACE_AFTER

    @property
    def space_before(self) -> bool:
        return self.attach in _SPACE_BEFORE


def spoken_words(phrase: str) -> list[str]:
    """Split a spoken phrase into its words, in canonical spelling."""
    cleaned = strip_zwnj(normalize(phrase, digits="keep", zwnj=False))
    return [w for w in cleaned.split(" ") if w]


def spoken_key(phrase: str) -> str:
    """The string the matcher looks up.

    The words are *concatenated*, not tupled, and that is the whole trick: a
    speaker saying "ری اکت" can come back from the recogniser as two words, as
    one word, or joined with a ZWNJ, and all three have to find React.  Keying on
    the joined form makes the lookup blind to that difference instead of needing
    one dictionary entry per spelling.
    """
    return "".join(spoken_words(phrase))


# The matcher joins up to this many input tokens even when every entry is a
# single word.  A one-word entry can still arrive as several tokens — the user
# writes "کیوبرنتیس" in their dictionary and the recogniser splits it — so the
# lookahead cannot be read off the entries' own word counts.
MIN_LOOKAHEAD = 3


class Lexicon:
    """Spoken phrase -> :class:`Entry`, with longest-phrase-first lookup."""

    def __init__(self) -> None:
        self._entries: dict[str, Entry] = {}
        self._max_len = MIN_LOOKAHEAD

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def max_phrase_len(self) -> int:
        """How many input tokens the matcher may join into one candidate key."""
        return self._max_len

    def add(self, phrase: str, entry: Entry) -> None:
        words = spoken_words(phrase)
        if not words:
            return
        self._entries["".join(words)] = entry
        self._max_len = max(self._max_len, len(words))

    def get(self, key: str) -> Entry | None:
        return self._entries.get(key)

    def phrases(self) -> Iterable[tuple[str, Entry]]:
        return self._entries.items()

    # -- loading ---------------------------------------------------------

    def load_terms(self, terms: dict[str, list[str]], *, source: str = "builtin") -> None:
        """Load a ``canonical -> [spoken forms]`` mapping (the glossary shape)."""
        for canonical, spoken in terms.items():
            if isinstance(spoken, str):
                spoken = [spoken]
            for form in spoken:
                self.add(form, Entry(text=canonical, attach="word", source=source))

    def load_symbols(self, symbols: list[dict], *, source: str = "builtin") -> None:
        """Load the punctuation-table shape."""
        for sym in symbols:
            entry = Entry(text=sym["text"], attach=sym.get("attach", "word"), source=source)
            for form in sym["say"]:
                self.add(form, entry)


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def builtin_path(name: str) -> Path:
    return Path(str(files("mlqvoice.text") / "data" / name))


def build_lexicon(
    *,
    glossary: bool = True,
    punctuation: bool = True,
    user_file: Path | None = None,
) -> Lexicon:
    """Assemble the lexicon the pipeline runs against.

    The user's file is read last so their spelling of a word beats ours.  A
    missing user file is normal and silent; a malformed one is not — it raises,
    because silently ignoring the dictionary somebody just edited is the kind of
    failure that looks like "the app ignored my word".
    """
    lex = Lexicon()
    if punctuation:
        lex.load_symbols(_read_json(builtin_path("punctuation.json"))["symbols"])
    if glossary:
        lex.load_terms(_read_json(builtin_path("programmer.json"))["terms"])

    if user_file is not None and user_file.exists():
        data = _read_json(user_file)
        if "symbols" in data:
            lex.load_symbols(data["symbols"], source="user")
        if "terms" in data:
            lex.load_terms(data["terms"], source="user")
    return lex
