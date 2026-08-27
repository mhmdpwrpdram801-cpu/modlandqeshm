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
from .phonetics import phrase_key

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
        # Phonetic keys are a *fallback* index, consulted only when the exact one
        # misses. A key that two different terms would both claim is dropped
        # rather than guessed at — see _phonetic_conflicts.
        self._phonetic: dict[str, Entry] = {}
        self._phonetic_conflicts: set[str] = set()
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

        sound = phrase_key(words)
        if not sound:
            return
        existing = self._phonetic.get(sound)
        if existing is not None and existing.text != entry.text:
            # Two terms that sound alike. Emitting either would be a coin flip,
            # so this key stops being usable for both of them.
            self._phonetic_conflicts.add(sound)
            self._phonetic.pop(sound, None)
        elif sound not in self._phonetic_conflicts:
            self._phonetic[sound] = entry

    def get(self, key: str) -> Entry | None:
        return self._entries.get(key)

    def block_sounds(self, words: Iterable[str]) -> int:
        """Refuse to sound-match anything that is an ordinary Persian word.

        Without this, folding ص onto س turned «صورت» — a face — into ``sort``.
        A word that is *deliberately* a dictionary entry is left alone: «درصد»
        really is how you say ``%``, and blocking it would break that.
        """
        blocked = 0
        for word in words:
            if self.get(spoken_key(word)) is not None:
                continue  # claimed on purpose by an exact entry
            sound = phrase_key(spoken_words(word))
            if sound and self._phonetic.pop(sound, None) is not None:
                blocked += 1
            if sound:
                self._phonetic_conflicts.add(sound)
        return blocked

    def get_by_sound(self, words: list[str]) -> Entry | None:
        """Fallback lookup: same sound, different spelling."""
        sound = phrase_key(words)
        if not sound or sound in self._phonetic_conflicts:
            return None
        return self._phonetic.get(sound)

    @property
    def phonetic_size(self) -> int:
        return len(self._phonetic)

    @property
    def phonetic_conflicts(self) -> set[str]:
        return set(self._phonetic_conflicts)

    def outputs(self) -> set[str]:
        """Every canonical word this lexicon can emit.

        Finglish conversion uses it as a skip-list: without it, pressing the
        button after dictating would turn the glossary's own ``commit`` back
        into ``کممیت``.
        """
        return {e.text for e in self._entries.values() if e.attach == "word"}

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


class DictionaryError(ValueError):
    """The user's own dictionary cannot be read, and here is which one and why.

    The bare ``JSONDecodeError`` this replaces was raised straight out of
    :class:`~mlqvoice.app.VoiceApp`'s constructor, where nothing caught it — so
    a ``--windowed`` build died with no window and no message. The tray menu
    invites people to edit this file in Notepad, which makes a trailing comma
    an ordinary Tuesday rather than an exotic accident.
    """


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _load_user_file(lex: Lexicon, path: Path) -> None:
    """Fold the user's own dictionary in, turning any breakage into one error.

    Four different failures live behind this call — bad JSON, a symbol with no
    ``text``, an ``attach`` the loader does not know, and a ``terms`` block that
    is not a mapping — and each raises a different builtin type from a different
    depth. Naming the file once here is what lets the caller show something
    useful instead of a traceback nobody sees.
    """
    try:
        data = _read_json(path)
        if not isinstance(data, dict):
            raise TypeError("فایل باید یک شیء JSON باشد")
        if "symbols" in data:
            lex.load_symbols(data["symbols"], source="user")
        if "terms" in data:
            terms = data["terms"]
            if not isinstance(terms, dict):
                raise TypeError("بخشِ terms باید یک شیء JSON باشد")
            lex.load_terms(terms, source="user")
    except json.JSONDecodeError as exc:
        raise DictionaryError(f"{path}: JSONِ سالم نیست — {exc}") from exc
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise DictionaryError(f"{path}: خوانده نشد — {exc}") from exc


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
    missing user file is normal and silent; a malformed one is not — it raises
    :class:`DictionaryError`, because silently ignoring the dictionary somebody
    just edited is the kind of failure that looks like "the app ignored my word".

    The *builtin* files are deliberately not wrapped: if one of those is broken
    the build is broken, and dressing that up as a user-facing message would
    send somebody hunting through their own file for our bug.
    """
    lex = Lexicon()
    if punctuation:
        lex.load_symbols(_read_json(builtin_path("punctuation.json"))["symbols"])
    if glossary:
        lex.load_terms(_read_json(builtin_path("programmer.json"))["terms"])

    # Guard the sound index *after* the terms are in, so a word that a term
    # legitimately claims is recognised as such.
    common = _read_json(builtin_path("fa_common.json"))["words"]
    lex.block_sounds(common)

    if user_file is not None and user_file.exists():
        _load_user_file(lex, user_file)
    return lex
