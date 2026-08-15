"""Persian text normalisation.

Google's ``fa-IR`` recogniser does not emit one canonical spelling: the same word
can come back with the Arabic ``ي``/``ك`` instead of the Persian ``ی``/``ک``, with
Arabic-Indic digits instead of Persian ones, and with a plain space where a
zero-width non-joiner belongs.  Every later stage (glossary lookup, punctuation,
the user's own dictionary) matches on exact strings, so normalising *first* is
what makes those stages behave predictably.
"""

from __future__ import annotations

import re

ZWNJ = "‌"

# Arabic letters that have a Persian counterpart.  No key may also be a value.
_LETTER_MAP = {
    "ك": "ک",  # ARABIC KAF ك          -> PERSIAN KEHEH ک
    "ي": "ی",  # ARABIC YEH ي          -> FARSI YEH ی
    "ى": "ی",  # ALEF MAKSURA ى        -> FARSI YEH ی
    "ە": "ه",  # AE ە                  -> HEH ه
    "ة": "ه",  # TEH MARBUTA ة         -> HEH ه
    "أ": "ا",  # ALEF WITH HAMZA ABOVE أ -> ALEF ا
    "إ": "ا",  # ALEF WITH HAMZA BELOW إ -> ALEF ا
    "ٱ": "ا",  # ALEF WASLA ٱ          -> ALEF ا
    "ؤ": "و",  # WAW WITH HAMZA ؤ      -> WAW و
}

# Harakat (U+064B..U+0655), superscript alef (U+0670) and tatweel (U+0640) carry
# no meaning in dictated text.  The range deliberately stops before U+0660: those
# are the Arabic-Indic digits and they must survive to reach the digit stage.
_STRIP_RE = re.compile("[ً-ٰٕـ]")

# Persian/Arabic letters *excluding* both digit blocks (U+0660..U+0669 and
# U+06F0..U+06F9), so that a number never counts as a word for the ZWNJ rules.
_LETTER = "ء-غف-يٮٯٱ-ۓەۥۦۮۯۺ-ۿ"

_ARABIC_INDIC = "٠١٢٣٤٥٦٧٨٩"
_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_LATIN_DIGITS = "0123456789"

_TO_PERSIAN_DIGITS = str.maketrans(_ARABIC_INDIC + _LATIN_DIGITS, _PERSIAN_DIGITS * 2)
_TO_LATIN_DIGITS = str.maketrans(_ARABIC_INDIC + _PERSIAN_DIGITS, _LATIN_DIGITS * 2)


def to_persian_digits(text: str) -> str:
    """Digits as a Persian reader expects them. Display only — never storage."""
    return text.translate(_TO_PERSIAN_DIGITS)


# ``می``/``نمی`` bind to the verb that follows them with a ZWNJ.
_PREFIX_RE = re.compile(rf"(?<![{_LETTER}])(ن?می)\s+(?=[{_LETTER}]{{2,}})")

# Suffixes that bind to the previous word with a ZWNJ.  Deliberately short: every
# extra entry is a chance to glue two genuinely separate words together, and a
# wrong join is more annoying than a missing one.
_SUFFIXES = ("هایی", "های", "ها", "ترین", "تر")
_SUFFIX_RE = re.compile(
    rf"(?<![{_LETTER}])([{_LETTER}]{{3,}})\s+({'|'.join(_SUFFIXES)})(?![{_LETTER}])"
)


def _apply_letters(text: str) -> str:
    return "".join(_LETTER_MAP.get(ch, ch) for ch in text)


def apply_zwnj(text: str) -> str:
    """Glue Persian prefixes and suffixes to their host word with a ZWNJ."""
    text = _PREFIX_RE.sub(lambda m: m.group(1) + ZWNJ, text)
    # A word may carry more than one of these; repeat until the text stops moving.
    for _ in range(3):
        joined = _SUFFIX_RE.sub(lambda m: m.group(1) + ZWNJ + m.group(2), text)
        if joined == text:
            break
        text = joined
    return text


def strip_zwnj(text: str) -> str:
    """Remove every ZWNJ — used to build lookup keys, not for display."""
    return text.replace(ZWNJ, "")


def normalize(text: str, *, digits: str = "latin", zwnj: bool = True) -> str:
    """Return *text* in canonical Persian spelling.

    ``digits`` is ``"latin"`` (default — this tool is aimed at people writing
    code), ``"fa"`` for Persian digits, or ``"keep"`` to leave them alone.
    """
    if digits not in ("latin", "fa", "keep"):
        raise ValueError(f"unknown digits mode: {digits!r}")

    text = _apply_letters(text)
    text = _STRIP_RE.sub("", text)

    if digits == "latin":
        text = text.translate(_TO_LATIN_DIGITS)
    elif digits == "fa":
        text = text.translate(_TO_PERSIAN_DIGITS)

    # A ZWNJ next to a space is always noise, and doubled ZWNJ is invisible junk.
    text = re.sub(f"{ZWNJ}+", ZWNJ, text)
    text = re.sub(f"[^\\S\\n]*{ZWNJ}[^\\S\\n]*", ZWNJ, text)

    if zwnj:
        text = apply_zwnj(text)

    # Collapse runs of spaces/tabs but keep newlines, which carry meaning once the
    # punctuation stage has turned "خط جدید" into one.
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()
