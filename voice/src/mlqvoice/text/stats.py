"""Counting what actually happens, so the dictionary can be judged on evidence.

``learned.json`` records the corrections — the failures. That is only ever half
a fraction: it says a word came out wrong twelve times, and nothing at all about
how many dictations went by untouched. Without the denominator there is no way
to answer the one question worth asking, which is whether any of this is
working.

**What this deliberately does not store: a single word the user dictated.**
Counts, and the dictionary's *own* canonical outputs (``commit``, ``.``) — never
their text, never the recogniser's. So the answer to "what is in this file" is
"numbers and words we shipped ourselves", and it stays true without anybody
having to audit it later.

Buckets are per day so a trend is visible without keeping a row per dictation,
and old days fall off the end so a machine used daily does not grow a log
forever.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

#: Days of history to keep. Long enough to see a month-over-month trend, short
#: enough that the file stays a few kilobytes on a machine used every day.
MAX_DAYS = 120

#: Distinct dictionary terms to track. The glossary is a few hundred entries and
#: only the ones that fire are stored, but a runaway user dictionary should not
#: be able to grow this without limit either.
MAX_TERMS = 500


@dataclass
class Day:
    """One day's totals."""

    dictations: int = 0
    edited: int = 0
    words: int = 0
    seconds: int = 0

    def add(self, *, words: int, edited: bool, seconds: int) -> None:
        self.dictations += 1
        self.edited += 1 if edited else 0
        self.words += words
        self.seconds += seconds


@dataclass
class Stats:
    days: dict[str, Day] = field(default_factory=dict)
    terms: dict[str, int] = field(default_factory=dict)

    # -- totals ----------------------------------------------------------

    @property
    def dictations(self) -> int:
        return sum(d.dictations for d in self.days.values())

    @property
    def edited(self) -> int:
        return sum(d.edited for d in self.days.values())

    @property
    def words(self) -> int:
        return sum(d.words for d in self.days.values())

    @property
    def seconds(self) -> int:
        return sum(d.seconds for d in self.days.values())

    @property
    def clean_rate(self) -> float | None:
        """Share of dictations inserted with no hand-editing at all.

        ``None`` rather than 1.0 when there is nothing to divide: a rate made up
        out of zero samples is the kind of number that gets quoted later.
        """
        if not self.dictations:
            return None
        return (self.dictations - self.edited) / self.dictations

    @property
    def words_per_minute(self) -> float | None:
        if self.seconds <= 0:
            return None
        return self.words * 60 / self.seconds

    def top_terms(self, limit: int = 15) -> list[tuple[str, int]]:
        return sorted(self.terms.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def _prune(stats: Stats) -> None:
    for key in sorted(stats.days)[:-MAX_DAYS] if len(stats.days) > MAX_DAYS else []:
        del stats.days[key]
    if len(stats.terms) > MAX_TERMS:
        keep = dict(sorted(stats.terms.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_TERMS])
        stats.terms.clear()
        stats.terms.update(keep)


def load(path: Path) -> Stats:
    """Read the file; anything unreadable is simply an empty history.

    Forgiving on purpose, like the learning file and unlike the config: the user
    never wrote this by hand, so a damaged one is our problem, not theirs, and
    it must never be the reason the app fails to start.
    """
    if not path.exists():
        return Stats()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Stats()
    if not isinstance(data, dict):
        return Stats()

    stats = Stats()
    for key, row in (data.get("days") or {}).items():
        if not isinstance(row, dict):
            continue
        try:
            stats.days[str(key)] = Day(
                dictations=int(row.get("dictations", 0)),
                edited=int(row.get("edited", 0)),
                words=int(row.get("words", 0)),
                seconds=int(row.get("seconds", 0)),
            )
        except (TypeError, ValueError):
            continue
    for term, count in (data.get("terms") or {}).items():
        try:
            stats.terms[str(term)] = int(count)
        except (TypeError, ValueError):
            continue
    return stats


def save(path: Path, stats: Stats) -> None:
    _prune(stats)
    payload = {
        "version": 1,
        "note": (
            "شمارشِ استفاده‌ی خودت. هیچ متنی که گفته‌ای اینجا نیست — فقط عدد و "
            "واژه‌های خودِ دیکشنری. جایی فرستاده نمی‌شود."
        ),
        "days": {
            key: {
                "dictations": day.dictations,
                "edited": day.edited,
                "words": day.words,
                "seconds": day.seconds,
            }
            for key, day in sorted(stats.days.items())
        },
        "terms": dict(sorted(stats.terms.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record(
    path: Path,
    *,
    words: int,
    edited: bool,
    seconds: int = 0,
    terms: list[str] | None = None,
    today: str | None = None,
) -> None:
    """Add one dictation to the tally.

    *edited* is the interesting bit: it is the difference between what the
    pipeline produced and what the user was willing to insert, which is the only
    honest measure of whether the dictionary did its job.
    """
    stats = load(path)
    key = today or date.today().isoformat()
    stats.days.setdefault(key, Day()).add(words=words, edited=edited, seconds=max(0, seconds))
    for term in terms or []:
        stats.terms[term] = stats.terms.get(term, 0) + 1
    save(path, stats)
