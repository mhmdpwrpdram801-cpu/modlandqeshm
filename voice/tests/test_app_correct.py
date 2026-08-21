"""The wiring: when a correction runs, and what happens while it has not.

``test_correct.py`` proves the call. What is left is the part that can lose a
sentence — the gap between "you stopped talking" and "the corrected text is in
the box". Press "تمام شد" inside that gap and the naive version inserts
everything *except* the sentence you just said.

The order also matters and is easy to get backwards: by the time the pipeline
has run, «کامیت کن نقطه» is ``commit .``, and a language model shown that will
helpfully turn it back into a sentence. Correction has to see the raw Persian.
"""

from __future__ import annotations

import pytest

from mlqvoice import inject


class Spy:
    """Stands in for the Gemini call, recording exactly what it was shown."""

    def __init__(self, answer=None, enabled=True):
        self.seen: list[str] = []
        self._answer = answer
        self.enabled = enabled

    def correct(self, text: str) -> str:
        self.seen.append(text)
        if self._answer is None:
            return text
        return self._answer(text) if callable(self._answer) else self._answer


@pytest.fixture
def app(make_app, monkeypatch):
    voice = make_app(gemini_key="test-key")
    monkeypatch.setattr(inject, "insert", lambda *a, **k: None)
    return voice


def swap(voice, spy) -> None:
    """Replace the real corrector, keeping the worker thread that is already up."""
    voice.corrector = spy


class TestItIsOffUnlessAskedFor:
    def test_no_key_means_no_correction(self, make_app):
        voice = make_app()
        assert not voice.correcting
        assert voice._corr_thread is None

    def test_a_key_turns_it_on(self, app):
        assert app.correcting
        assert app._corr_thread is not None

    def test_the_setting_can_switch_it_off_even_with_a_key(self, make_app):
        voice = make_app(gemini_key="test-key", correct=False)
        assert not voice.correcting
        assert voice._corr_thread is None

    def test_without_correction_the_text_still_arrives(self, make_app):
        # The path everyone who never sets a key takes: unchanged from before.
        voice = make_app()
        voice.start_recording()
        voice._on_result("سلام", True)
        assert "سلام" in voice.overlay.text()


class TestWhatGeminiIsShown:
    def test_it_sees_the_raw_persian_not_the_glossary_output(self, app):
        # The trap: "کامیت کن نقطه" becomes "commit ." downstream. A model given
        # that would write a sentence back.
        spy = Spy()
        swap(app, spy)
        app.start_recording()
        app._on_result("کامیت کن نقطه", True)
        app._await_corrections()
        assert spy.seen == ["کامیت کن نقطه"]

    def test_and_the_glossary_still_runs_on_what_comes_back(self, app):
        swap(app, Spy())
        app.start_recording()
        app._on_result("کامیت کن نقطه", True)
        app._await_corrections()
        assert "commit" in app.overlay.text()

    def test_interim_guesses_are_never_sent(self, app):
        # They are rewritten several times a second; correcting them would spend
        # a request per keystroke-worth of speech and rewrite the box underneath
        # the user.
        spy = Spy()
        swap(app, spy)
        app.start_recording()
        for _ in range(5):
            app._on_result("سلام", False)
        assert spy.seen == []


class TestTheBoxShowsTheCorrection:
    def test_the_corrected_sentence_is_what_lands(self, app):
        swap(app, Spy(answer="سلام چطوری"))
        app.start_recording()
        app._on_result("سلام چطور", True)
        app._await_corrections()
        assert "سلام چطوری" in app.overlay.text()

    def test_the_uncorrected_sentence_does_not_flash_up_first(self, app):
        # Held back rather than shown and rewritten: the box is also the edit
        # buffer, and text that changes under a cursor is worse than text that
        # is a second late.
        swap(app, Spy(answer="سلام چطوری"))
        app.start_recording()
        app._on_result("سلام چطور", True)
        assert app.overlay.text().strip() == ""
        app._await_corrections()
        assert "سلام چطوری" in app.overlay.text()

    def test_two_sentences_keep_the_order_they_were_spoken(self, app):
        swap(app, Spy())
        app.start_recording()
        app._on_result("جمله‌ی اول", True)
        app._on_result("جمله‌ی دوم", True)
        app._await_corrections()
        text = app.overlay.text()
        assert text.index("اول") < text.index("دوم")


class TestNothingIsLostAtTheEnd:
    def test_pressing_done_waits_for_a_correction_still_in_flight(self, app, monkeypatch):
        written: list[str] = []
        monkeypatch.setattr(inject, "insert", lambda hwnd, text, **kw: written.append(text))
        swap(app, Spy(answer="سلام چطوری"))
        app.start_recording()
        app._on_result("سلام چطور", True)
        # Deliberately *before* the correction has landed — this is the gap the
        # whole feature is not allowed to lose a sentence in.
        app._insert(app.overlay.text())
        assert written, "چیزی نوشته نشد"
        assert "سلام چطوری" in written[0], f"نوشته شد: {written[0]!r}"

    def test_a_correction_that_never_returns_does_not_hang_the_app(self, make_app, monkeypatch):
        # The corrector has its own timeout, but the wait must end even if the
        # worker is wedged. Losing the improvement is fine; losing the app is not.
        voice = make_app(gemini_key="test-key", correct_timeout=0)
        monkeypatch.setattr(inject, "insert", lambda *a, **k: None)
        voice._corr_pending = 1  # a reply that will never come
        voice._await_corrections()
        assert voice._corr_pending == 0


class TestSessionsDoNotBleedIntoEachOther:
    def test_a_late_correction_from_a_finished_dictation_is_dropped(self, app):
        # The user finished, the box was cleared, and only then does the old
        # sentence come back from Gemini. Appending it would drop a stranded
        # line into whatever they are dictating now.
        app.start_recording()
        gen = app._corr_gen
        app._new_session()
        app._on_corrected(gen, "سلام", "سلام چطوری")
        assert "سلام" not in app.overlay.text()

    def test_the_current_dictation_still_accepts_its_own(self, app):
        app.start_recording()
        app._on_corrected(app._corr_gen, "سلام", "سلام چطوری")
        assert "سلام چطوری" in app.overlay.text()


class TestTheWorkerIsCleanedUp:
    def test_quitting_stops_the_thread(self, app, monkeypatch):
        from PySide6.QtWidgets import QApplication

        monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: None))
        monkeypatch.setattr(type(app.listener), "stop", lambda _self: None)
        monkeypatch.setattr(type(app.bridge), "stop", lambda _self: None)
        app.quit()
        assert app._corr_thread is None

    def test_stopping_twice_is_harmless(self, app):
        app.stop_correcting()
        app.stop_correcting()
        assert app._corr_thread is None
