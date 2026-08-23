"""Learning dictionary entries from the corrections the user makes by hand.

Every other source of entries is a guess about how Google will spell a word.
This one is not: when somebody dictates, edits the box, and presses "بنویس",
the difference between what the recogniser said and what they actually wanted
*is* the missing dictionary entry.

The diff runs against the **raw** recogniser output rather than the pipeline's
own output, which makes one rule cover both cases at once: a word the glossary
never knew, and a word the glossary got wrong.  Anything the lexicon already
produces on its own is dropped, so the only things that survive are genuinely
new.

Nothing here leaves the machine.  Suggestions live in the user's own profile
directory, are never applied without being asked for, and can be wiped with one
command.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

from ..paths import write_atomic
from .lexicon import Lexicon
from .normalize import normalize
from .pipeline import Options, transform

#: A correction spanning more words than this is a rewrite, not a vocabulary
#: gap, and turning it into a dictionary rule would fire in the wrong places.
MAX_SPAN = 3

#: Stop the file growing without bound on a machine used every day.
MAX_STORED = 500


@dataclass(frozen=True)
class Suggestion:
    """One proposed dictionary entry, with how often it has been seen."""

    spoken: str
    replacement: str
    count: int = 1

    @property
    def key(self) -> tuple[str, str]:
        return (self.spoken, self.replacement)


def _words(text: str) -> list[str]:
    return [w for w in normalize(text, digits="keep", zwnj=False).split(" ") if w]


def _plausible(spoken: list[str], replacement: list[str]) -> bool:
    if not spoken or not replacement:
        return False
    if len(spoken) > MAX_SPAN or len(replacement) > MAX_SPAN:
        return False
    joined = "".join(spoken)
    # A span of pure digits or punctuation is not a word anybody dictated.
    if not any(ch.isalpha() for ch in joined):
        return False
    return len(joined) >= 2


def suggest(
    raw: str,
    final: str,
    lex: Lexicon,
    opts: Options | None = None,
) -> list[Suggestion]:
    """Propose entries from one dictation, given what was heard and what was kept.

    ``raw`` is the recogniser's own words; ``final`` is the text the user chose
    to insert.
    """
    opts = opts or Options()
    heard, wanted = _words(raw), _words(final)
    if not heard or not wanted:
        return []

    out: list[Suggestion] = []
    matcher = SequenceMatcher(a=heard, b=wanted, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        spoken, replacement = heard[i1:i2], wanted[j1:j2]
        if not _plausible(spoken, replacement):
            continue

        said = " ".join(spoken)
        want = " ".join(replacement)
        # If the pipeline already turns this into what the user wanted, there is
        # nothing to learn — the correction was about something else nearby.
        if transform(said, lex, opts) == want:
            continue
        out.append(Suggestion(spoken=said, replacement=want))
    return out


# -- storage -------------------------------------------------------------


def load(path: Path) -> list[Suggestion]:
    """Read stored suggestions; a missing or unreadable file is simply empty.

    This one *is* forgiving where the user's dictionary is not: a corrupt
    learning file must never stop the app from starting, because unlike the
    dictionary the user never wrote it by hand.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data["suggestions"]
    except (json.JSONDecodeError, KeyError, TypeError, OSError):
        return []
    out = []
    for row in rows:
        try:
            out.append(
                Suggestion(
                    spoken=str(row["spoken"]),
                    replacement=str(row["replacement"]),
                    count=int(row.get("count", 1)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def save(path: Path, suggestions: list[Suggestion]) -> None:
    ranked = sorted(suggestions, key=lambda s: (-s.count, s.spoken))[:MAX_STORED]
    payload = {
        "version": 1,
        "note": "پیشنهادهایی که از ویرایش‌های خودت درآمده. جایی فرستاده نمی‌شود.",
        "suggestions": [asdict(s) for s in ranked],
    }
    write_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def merge(existing: list[Suggestion], fresh: list[Suggestion]) -> list[Suggestion]:
    """Fold new suggestions into the stored ones, counting repeats.

    The count is the whole point: correcting the same word twice is evidence,
    correcting it once might have been a typo.
    """
    by_key = {s.key: s for s in existing}
    for item in fresh:
        current = by_key.get(item.key)
        by_key[item.key] = (
            Suggestion(item.spoken, item.replacement, current.count + 1) if current else item
        )
    return list(by_key.values())


def record(path: Path, raw: str, final: str, lex: Lexicon, opts: Options | None = None) -> int:
    """Learn from one dictation. Returns how many suggestions it produced."""
    fresh = suggest(raw, final, lex, opts)
    if not fresh:
        return 0
    save(path, merge(load(path), fresh))
    return len(fresh)


def as_dictionary(suggestions: list[Suggestion], *, min_count: int = 1) -> dict[str, list[str]]:
    """Shape accepted suggestions like the user dictionary's ``terms`` block."""
    terms: dict[str, list[str]] = {}
    for item in sorted(suggestions, key=lambda s: (-s.count, s.spoken)):
        if item.count < min_count:
            continue
        forms = terms.setdefault(item.replacement, [])
        if item.spoken not in forms:
            forms.append(item.spoken)
    return terms


class DictionaryUnreadable(ValueError):
    """The user's own dictionary is not something we can safely rewrite."""


def apply_to_dictionary(target: Path, suggestions: list[Suggestion], *, min_count: int = 1) -> int:
    """Fold accepted suggestions into the user's dictionary; return forms added.

    Shared by the command line and the tray menu rather than written twice. Two
    copies of "merge into a JSON file" drift, and the way they drift is that one
    of them starts losing entries.

    **Refuses rather than repairs.** The user writes that file by hand, so a
    file we cannot parse is a file we must not overwrite — rebuilding it from a
    half-parse would silently throw away entries they typed themselves. The
    caller is expected to say so out loud (OPS-03).
    """
    accepted = as_dictionary(suggestions, min_count=min_count)
    if not accepted:
        return 0

    data: dict = {}
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DictionaryUnreadable(f"JSONِ سالم نیست — {exc}") from exc
        if not isinstance(data, dict):
            raise DictionaryUnreadable("فایلِ دیکشنری باید یک شیء JSON باشد")

    terms = data.setdefault("terms", {})
    if not isinstance(terms, dict):
        raise DictionaryUnreadable("بخشِ terms در دیکشنری باید یک شیء JSON باشد")

    added = 0
    for canonical, forms in accepted.items():
        current = terms.setdefault(canonical, [])
        if not isinstance(current, list):
            raise DictionaryUnreadable(f"مدخلِ {canonical!r} باید فهرست باشد")
        for form in forms:
            if form not in current:
                current.append(form)
                added += 1
    write_atomic(target, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return added
