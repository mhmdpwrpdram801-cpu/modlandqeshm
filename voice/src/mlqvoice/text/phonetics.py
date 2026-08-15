"""Folding Persian spelling variants onto one key.

Measured problem: 63% of the glossary's terms carry exactly one spelling, and a
sweep of plausible respellings showed **98% of them miss**.  That is not a
vocabulary gap — every one of those words is already in the dictionary.  It is
that Google's ``fa-IR`` output does not commit to one orthography, and exact
matching demands that it does.

Persian writes several distinct Arabic letters that all sound the same to a
Persian speaker, and a transliterated English word can legitimately use either:
``کامیت``/``کامیط``, ``ریکوئست``/``ریکوست``, ``هاب``/``حاب``.  Folding those
classes together turns one dictionary entry into every spelling of itself.

This is deliberately a *fallback*: the pipeline tries exact keys first, so
nothing that worked before can change, and a phonetic key that would be
ambiguous is dropped rather than guessed at (see :class:`~.lexicon.Lexicon`).
"""

from __future__ import annotations

import re

from .normalize import normalize, strip_zwnj

# Letters that share a sound in Persian. The left-hand side collapses to the
# right. These are exactly the pairs a speaker cannot hear the difference
# between, which is why a recogniser picks between them arbitrarily.
_FOLD = {
    "ط": "ت",
    "ص": "س",
    "ث": "س",
    "ذ": "ز",
    "ض": "ز",
    "ظ": "ز",
    "ح": "ه",
    "غ": "ق",
    "آ": "ا",
    "أ": "ا",
    "إ": "ا",
    "ع": "ا",  # silent or alef-like inside loanwords
    "ء": "",
    "ئ": "",
    "ؤ": "و",
}

# A word may open with either spelling of the same initial vowel:
# "ایمپورت" and "امپورت" are the same word said the same way.
_INITIAL_EI = re.compile(r"^ای")

_DOUBLED = re.compile(r"(.)\1+")


#: Below this many letters a key is more likely to collide with an ordinary
#: Persian word than to identify a term, so it is not indexed at all.
MIN_KEY_LEN = 3


def _fold(word: str) -> str:
    """The folding itself, with no length judgement."""
    folded = strip_zwnj(normalize(word, digits="keep", zwnj=False))
    folded = "".join(_FOLD.get(ch, ch) for ch in folded)
    folded = _INITIAL_EI.sub("ا", folded)
    return _DOUBLED.sub(r"\1", folded).strip()


def phonetic_key(word: str) -> str:
    """Fold one word onto the key every spelling of it shares."""
    folded = _fold(word)
    return folded if len(folded) >= MIN_KEY_LEN else ""


def phrase_key(words: list[str]) -> str:
    """The phonetic key for a run of words, joined the way the matcher joins.

    The length rule applies to the *joined* key, not to each word. Applying it
    per word threw away every multi-word term containing a short one — "ری بیس",
    "چک اوت", "ای پی آی" — even when the two keys were character-identical.
    """
    joined = "".join(_fold(w) for w in words)
    return joined if len(joined) >= MIN_KEY_LEN else ""
