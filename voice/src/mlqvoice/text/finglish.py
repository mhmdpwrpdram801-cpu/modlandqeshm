"""Finglish to Persian: ``salam chetori`` -> ``سلام چطوری``.

This is transliteration by sound, and Persian orthography makes it genuinely
lossy in one direction: short vowels are simply not written.  ``bordan`` is
``بردن`` — the *o* and the *a* leave no trace — while the long vowels in
``khoobam`` do, as ``خوبم``.  So the rules below drop ``a``/``e``/``o`` in the
middle of a word and keep ``aa``/``oo``/``u``/``i``/``ee``.

That convention is what most people already type, but it cannot be right every
time: somebody who writes ``khob`` for ``خوب`` has left out the length, and no
rule can put it back.  For the words that get typed most, an exception table
short-circuits the rules — and for everything else the output is a good guess
that the user can fix in the box before inserting.

**Never applied automatically.**  The pipeline's own output is full of Latin on
purpose (``commit``, ``database``), and transliterating that would undo the
entire glossary.  It runs only when the user asks for it, and even then it steps
over anything that looks like code or a known term.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from itertools import product
from pathlib import Path

from .phonetics import phonetic_key

# Longest first: "kh" must beat "k", "aa" must beat "a".
_DIGRAPHS: tuple[tuple[str, str], ...] = (
    ("kh", "خ"),
    ("gh", "ق"),
    ("sh", "ش"),
    ("ch", "چ"),
    ("zh", "ژ"),
    ("ph", "ف"),
    ("aa", "ا"),
    ("ao", "او"),
    ("oo", "و"),
    ("ou", "و"),
    ("ee", "ی"),
    ("ei", "ی"),
    ("ai", "ای"),
    ("ie", "ی"),
)

_SINGLE: dict[str, str] = {
    "a": "",  # short vowels leave no letter mid-word
    "e": "",
    "o": "",
    "i": "ی",
    "u": "و",
    "b": "ب",
    "p": "پ",
    "t": "ت",
    "s": "س",
    "j": "ج",
    "h": "ه",
    "d": "د",
    "z": "ز",
    "r": "ر",
    "f": "ف",
    "k": "ک",
    "g": "گ",
    "l": "ل",
    "m": "م",
    "n": "ن",
    "v": "و",
    "w": "و",
    "y": "ی",
    "q": "ق",
    "x": "خ",
    "c": "ک",
    "'": "",
    "`": "",
}

#: A word that starts with a vowel needs an alef to carry it.
_INITIAL: tuple[tuple[str, str], ...] = (
    ("aa", "آ"),
    ("oo", "او"),
    ("ou", "او"),
    ("ei", "ای"),
    ("ee", "ای"),
    ("ai", "ای"),
    ("i", "ای"),
    ("u", "او"),
    ("a", "ا"),
    ("e", "ا"),
    ("o", "ا"),
)

#: A trailing "e"/"eh" is the silent he: ``khune`` -> ``خونه``.
_FINAL_HE = re.compile(r"(?:eh|e)$")
#: A trailing long "a" keeps its alef: ``inja`` -> ``اینجا``.
_FINAL_AA = re.compile(r"(?:aa|a)$")

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'`]*")

#: Tokens that are code, not Finglish, and must be left exactly as typed.
_LOOKS_LIKE_CODE = re.compile(r"[0-9_./\\@#$%<>=+*(){}\[\]]|(?:[a-z][A-Z])")


def _load_exceptions() -> dict[str, str]:
    path = Path(str(files("mlqvoice.text") / "data" / "finglish.json"))
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)["words"]


_EXCEPTIONS: dict[str, str] | None = None


def exceptions() -> dict[str, str]:
    global _EXCEPTIONS
    if _EXCEPTIONS is None:
        _EXCEPTIONS = _load_exceptions()
    return _EXCEPTIONS


#: Short vowels that are sometimes really long ones the writer did not double.
#: "ketab" is کتاب, not کتب — but "barf" is برف, not بارف, and no rule tells them
#: apart. So both readings are generated and the known-word list picks.
_MAYBE_LONG = {"a": "ا", "o": "و"}

#: Above this many ambiguous vowels the candidate set stops being worth building.
_MAX_AMBIGUOUS = 5

_KNOWN_WORDS: frozenset[str] | None = None


def known_words() -> frozenset[str]:
    """The vocabulary the arbiter judges candidate readings against.

    Deliberately a *different* file from the phonetic guard list. That one is a
    blocklist — every word in it makes the glossary's sound matching stricter —
    so growing it has a cost. This one only ever makes transliteration better,
    so it can be as large as we can make it.
    """
    global _KNOWN_WORDS
    if _KNOWN_WORDS is None:
        path = Path(str(files("mlqvoice.text") / "data" / "fa_vocab.json"))
        with path.open(encoding="utf-8") as fh:
            _KNOWN_WORDS = frozenset(json.load(fh)["words"])
    return _KNOWN_WORDS


_KNOWN_BY_SOUND: dict[str, str] | None = None


def known_by_sound() -> dict[str, str]:
    """Known Persian words indexed by the sound-folded key.

    Finglish cannot say whether a ``t`` is ت or ط, an ``s`` س or ص — the same
    ambiguity the glossary's phonetic layer already folds away. Reusing it here
    lets ``ghatar`` find قطار instead of stopping at قتر. Keys two different
    words would both claim are dropped, because guessing between them is a coin
    flip.
    """
    global _KNOWN_BY_SOUND
    if _KNOWN_BY_SOUND is None:
        index: dict[str, str] = {}
        clashes: set[str] = set()
        for word in known_words():
            key = phonetic_key(word)
            if not key:
                continue
            if key in index and index[key] != word:
                clashes.add(key)
            index[key] = word
        for key in clashes:
            index.pop(key, None)
        _KNOWN_BY_SOUND = index
    return _KNOWN_BY_SOUND


def _candidates(body: str, tail: str, prefix: str) -> list[str]:
    """Every reading of *body* where an ambiguous vowel is short or long."""
    slots = [i for i, ch in enumerate(body) if ch in _MAYBE_LONG]
    if not slots or len(slots) > _MAX_AMBIGUOUS:
        return []
    out = []
    for choice in product((False, True), repeat=len(slots)):
        longs = {slot for slot, take in zip(slots, choice, strict=True) if take}
        out.append(prefix + _render(body, longs) + tail)
    return out


def _render(body: str, longs: frozenset[int] | set[int] = frozenset()) -> str:
    """Letters for *body*, treating the vowels at *longs* as long ones."""
    out: list[str] = []
    i = 0
    while i < len(body):
        for pair, letters in _DIGRAPHS:
            if body.startswith(pair, i):
                out.append(letters)
                i += len(pair)
                break
        else:
            ch = body[i]
            if i in longs and ch in _MAYBE_LONG:
                out.append(_MAYBE_LONG[ch])
            else:
                out.append(_SINGLE.get(ch, ch))
            i += 1
    return "".join(out)


def _split(lowered: str) -> tuple[str, str, str]:
    """Split into (initial-vowel letters, body, final-vowel letters)."""
    prefix = ""
    start = 0
    for pre, letters in _INITIAL:
        if lowered.startswith(pre):
            prefix, start = letters, len(pre)
            break

    body, tail = lowered[start:], ""
    # Word-final vowels are the one place a short vowel does leave a mark.
    if len(body) > 1:
        if match := _FINAL_HE.search(body):
            tail, body = "ه", body[: match.start()]
        elif match := _FINAL_AA.search(body):
            tail, body = "ا", body[: match.start()]
    return prefix, body, tail


def convert_word(word: str) -> str:
    """Transliterate one Latin word. Returns it unchanged if it is not Finglish."""
    if not word or not _LATIN_WORD.fullmatch(word):
        return word

    lowered = word.lower()
    known = exceptions().get(lowered)
    if known is not None:
        return known

    prefix, body, tail = _split(lowered)
    plain = prefix + _render(body) + tail

    # A single "a" may be a short vowel that vanishes or a long one that becomes
    # an alef, and the spelling does not say which. Rather than guess, read it
    # both ways and let the known-word list decide; if none of the readings is a
    # word we know, keep the plain one.
    if plain in known_words():
        return plain

    readings = [plain, *_candidates(body, tail, prefix)]
    for candidate in readings:
        if candidate in known_words():
            return candidate
    # Still nothing spelled exactly right; try again by sound, which also
    # settles ت/ط, س/ص and the rest that Finglish cannot express.
    by_sound = known_by_sound()
    for candidate in readings:
        match = by_sound.get(phonetic_key(candidate))
        if match is not None:
            return match
    return plain or word


def convert(text: str, *, skip: set[str] | None = None) -> str:
    """Transliterate the Latin words in *text*, leaving everything else alone.

    ``skip`` holds terms that must survive untouched — the glossary's own output,
    so that pressing this after dictating does not turn ``commit`` into ``کامیت``.
    """
    skip_lower = {s.lower() for s in (skip or set())}

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.lower() in skip_lower:
            return word
        return convert_word(word)

    # Whole tokens are inspected first so that code-shaped ones survive intact.
    out: list[str] = []
    for token in re.split(r"(\s+)", text):
        if not token.strip() or _LOOKS_LIKE_CODE.search(token):
            out.append(token)
            continue
        out.append(_LATIN_WORD.sub(replace, token))
    return "".join(out)


def has_latin(text: str) -> bool:
    """Whether there is anything here worth converting."""
    return bool(_LATIN_WORD.search(text))
