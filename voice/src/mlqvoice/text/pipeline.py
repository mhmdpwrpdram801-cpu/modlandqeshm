"""Turning one chunk of recognised speech into the text that gets typed.

The stages, in order:

1. :func:`~mlqvoice.text.normalize.normalize` — one canonical spelling.
2. Longest-phrase-first lookup against the lexicon, so ``پول ریکوئست`` becomes
   ``pull request`` and not ``pull`` followed by a stray word.
3. Re-assembly, where each replacement decides its own spacing.

Everything here is pure: give it the same string and lexicon and it returns the
same output.  That is deliberate — it is the part of the app that can be tested
without a microphone, a browser or Windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from .lexicon import Entry, Lexicon, build_lexicon
from .normalize import normalize, strip_zwnj


@dataclass(frozen=True)
class Options:
    digits: str = "latin"
    zwnj: bool = True
    glossary: bool = True
    punctuation: bool = True


def _match_at(lex: Lexicon, keys: list[str], i: int) -> tuple[Entry, int] | None:
    """Longest lexicon phrase starting at token *i*, or ``None``.

    Candidate keys are built by joining consecutive tokens, which is what lets a
    two-word entry match speech that came back as one word (and the reverse).
    """
    longest = min(lex.max_phrase_len, len(keys) - i)
    for length in range(longest, 0, -1):
        entry = lex.get("".join(keys[i : i + length]))
        if entry is not None:
            return entry, length
    # Only now try sound. Exact spellings always win, so adding this index can
    # never change a match that already worked.
    for length in range(longest, 0, -1):
        entry = lex.get_by_sound(keys[i : i + length])
        if entry is not None:
            return entry, length
    return None


def render(entries: list[Entry]) -> str:
    """Join entries, letting each one decide whether it takes a space."""
    out: list[str] = []
    prev: Entry | None = None
    for entry in entries:
        if prev is not None and prev.space_after and entry.space_before:
            out.append(" ")
        out.append(entry.text)
        prev = entry
    text = "".join(out)
    # A symbol that eats the space around it can leave a dangling one at a line
    # break; clean that up rather than teach every attach kind about newlines.
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def transform_hits(
    text: str, lex: Lexicon | None = None, opts: Options | None = None
) -> tuple[str, list[str]]:
    """The pipeline's output, plus which dictionary entries actually fired.

    The second value answers a question nothing else could: *does the glossary
    earn its keep?* A dictionary can grow for years without anybody knowing
    which of its entries have ever been used. These are our own canonical
    outputs — ``commit``, ``.`` — never the user's words, so counting them
    carries nothing private with it.
    """
    opts = opts or Options()
    if lex is None:
        lex = build_lexicon(glossary=opts.glossary, punctuation=opts.punctuation)

    normalised = normalize(text, digits=opts.digits, zwnj=opts.zwnj)
    if not normalised:
        return "", []

    tokens = normalised.split(" ")
    # Match on ZWNJ-free keys so "ری‌اکت" and "ری اکت" both find React, but keep
    # the original token around for anything the lexicon does not know.
    keys = [strip_zwnj(t) for t in tokens]

    entries: list[Entry] = []
    hits: list[str] = []
    i = 0
    while i < len(tokens):
        hit = _match_at(lex, keys, i)
        if hit is not None:
            entry, length = hit
            entries.append(entry)
            hits.append(entry.text)
            i += length
        else:
            entries.append(Entry(text=tokens[i], attach="word"))
            i += 1
    return render(entries), hits


def transform(text: str, lex: Lexicon | None = None, opts: Options | None = None) -> str:
    """Run the full pipeline over one chunk of recognised speech."""
    return transform_hits(text, lex, opts)[0]
