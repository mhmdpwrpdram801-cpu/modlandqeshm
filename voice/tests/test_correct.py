"""The corrector, and every way it is allowed to fail.

Most of this file is about failure, and deliberately so. A correction that does
not happen costs the user nothing — they get exactly what they got yesterday.
A correction that *replaces their sentence with something else* is typed
straight into their document, and by then they have already stopped talking and
have no idea what was lost. So the interesting tests are not "does it fix a
typo", they are "what does it do when Gemini is down, slow, or too helpful".

No test here reaches the network: the opener is injected.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from mlqvoice.correct import MAX_CHARS, Corrector, _plausible


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def reply(text: str) -> FakeResponse:
    payload = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def opener_for(text: str, record: list | None = None):
    def opener(req, timeout=None):
        if record is not None:
            record.append((req, timeout))
        return reply(text)

    return opener


def boom(exc: Exception):
    def opener(_req, timeout=None):
        raise exc

    return opener


def make(text="", *, key="k", opener=None, **kw):
    return Corrector(key, opener=opener or opener_for(text), **kw)


class TestItCorrects:
    def test_the_corrected_sentence_comes_back(self):
        assert make("سلام چطوری").correct("سلام چطور") == "سلام چطوری"

    def test_a_sentence_that_was_already_right_is_untouched(self):
        assert make("سلام چطوری").correct("سلام چطوری") == "سلام چطوری"

    def test_the_key_travels_in_a_header_not_the_url(self):
        # Query strings turn up in proxy logs and crash reports; headers do not.
        seen: list = []
        make("سلام", opener=opener_for("سلام", seen)).correct("سلام")
        req, _ = seen[0]
        assert req.get_header("X-goog-api-key") == "k"
        assert "k" not in req.full_url

    def test_the_configured_timeout_is_the_one_used(self):
        seen: list = []
        make("سلام", opener=opener_for("سلام", seen), timeout=2.5).correct("سلام")
        assert seen[0][1] == 2.5

    def test_a_fenced_reply_is_unwrapped(self):
        # Told not to, models still sometimes wrap the answer in a code fence.
        assert make("```\nسلام چطوری\n```").correct("سلام چطور") == "سلام چطوری"


class TestNothingIsEverLost:
    """Every one of these must return the user's own words, unchanged."""

    def test_without_a_key_it_does_not_even_try(self):
        called = []
        c = Corrector("", opener=lambda *a, **k: called.append(1))
        assert c.correct("سلام") == "سلام"
        assert not called
        assert not c.enabled

    def test_a_network_error_keeps_the_original(self):
        c = make(opener=boom(urllib.error.URLError("no route")))
        assert c.correct("سلام چطور") == "سلام چطور"

    def test_a_timeout_keeps_the_original(self):
        assert make(opener=boom(TimeoutError())).correct("سلام چطور") == "سلام چطور"

    def test_an_http_error_keeps_the_original(self):
        err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        assert make(opener=boom(err)).correct("سلام چطور") == "سلام چطور"

    def test_broken_json_keeps_the_original(self):
        c = Corrector("k", opener=lambda *a, **k: FakeResponse(b"{ not json"))
        assert c.correct("سلام چطور") == "سلام چطور"

    def test_a_reply_with_no_candidates_keeps_the_original(self):
        c = Corrector("k", opener=lambda *a, **k: FakeResponse(b'{"candidates":[]}'))
        assert c.correct("سلام چطور") == "سلام چطور"

    def test_a_shape_we_did_not_expect_keeps_the_original(self):
        c = Corrector("k", opener=lambda *a, **k: FakeResponse(b'{"candidates":[{"x":1}]}'))
        assert c.correct("سلام چطور") == "سلام چطور"

    def test_an_empty_answer_keeps_the_original(self):
        assert make("   ").correct("سلام چطور") == "سلام چطور"

    def test_blank_input_is_not_sent_anywhere(self):
        called = []
        c = Corrector("k", opener=lambda *a, **k: called.append(1))
        assert c.correct("   ") == "   "
        assert not called

    def test_a_very_long_text_is_left_alone(self):
        # Not a dictated sentence; paying a round trip to reread it is not worth
        # the wait, and the guard is what stops a runaway paste going to Google.
        long = "ا" * (MAX_CHARS + 1)
        called = []
        c = Corrector("k", opener=lambda *a, **k: called.append(1))
        assert c.correct(long) == long
        assert not called


class TestItCorrectsRatherThanRewrites:
    """The dangerous failure: a model that answers instead of editing."""

    def test_an_explanation_is_refused(self):
        original = "سلام چطور"
        chatty = "متن شما ایراد نگارشی دارد. شکل درست آن «سلام چطوری» است."
        assert make(chatty).correct(original) == original

    def test_a_multi_line_answer_to_a_one_line_sentence_is_refused(self):
        original = "سلام چطور"
        assert make("سلام چطور\nتوضیح: …").correct(original) == original

    def test_a_much_shorter_answer_is_refused(self):
        # Dropping half the sentence is not a correction, it is a loss.
        original = "این یک جمله‌ی نسبتاً بلند برای آزمایش است"
        assert make("این").correct(original) == original

    def test_a_small_edit_is_allowed_through(self):
        original = "این یک جمله‌ی نسبتاً بلند برای آزمایش است"
        fixed = "این یک جمله‌ی نسبتاً بلند برای آزمایش بود"
        assert make(fixed).correct(original) == fixed


class TestThePlausibilityRule:
    @pytest.mark.parametrize(
        ("original", "reply", "ok"),
        [
            ("سلام", "سلام", True),
            ("سلام", "", False),
            ("سلام", "   ", False),
            ("سلام چطور", "سلام چطوری", True),
            ("خط یک", "خط یک\nخط دو", False),
            ("خط یک\nخط دو", "خط یک\nخط دو", True),
            ("۱۲۳۴۵۶۷۸۹۰", "۱۲", False),
            ("۱۲۳۴۵۶۷۸۹۰", "۱۲۳۴۵۶۷۸۹۰۱۲۳۴۵۶۷۸۹۰", False),
        ],
    )
    def test_cases(self, original, reply, ok):
        assert _plausible(original, reply) is ok
