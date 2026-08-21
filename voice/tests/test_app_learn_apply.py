"""Accepting what the app learned, from the tray, in one click.

The learning itself has worked for a while: dictate, fix the box by hand before
pressing «بنویس», and the difference is stored as a proposed dictionary entry.
What never worked was *accepting* those proposals — that needed
``mlqvoice learn --apply``, and on the installed build the name ``mlqvoice`` was
not even on PATH. A feature nobody can reach is a feature nobody has.

This matters more than it looks. Correction with Gemini needs an API key the
owner cannot get from here, so the dictionary is the only mechanism left that
makes dictation better over time — and it was the one that could not be
switched on.

Two things carry the weight below: the user's own dictionary is never rewritten
from a file we could not parse, and an accepted entry takes effect *now* rather
than at the next start.
"""

from __future__ import annotations

import json

import pytest

from mlqvoice.text import learning
from mlqvoice.text.learning import Suggestion

SUGGESTIONS = [
    Suggestion(spoken="کاربر", replacement="کاربرد", count=3),
    Suggestion(spoken="کیوب سی تی ال", replacement="kubectl", count=1),
]


@pytest.fixture
def paths(monkeypatch, tmp_path):
    learned = tmp_path / "learned.json"
    words = tmp_path / "dictionary.json"
    monkeypatch.setattr("mlqvoice.app.learned_file", lambda: learned)
    monkeypatch.setattr("mlqvoice.app.user_dictionary_file", lambda: words)
    learning.save(learned, SUGGESTIONS)
    return learned, words


def agree(monkeypatch, yes: bool = True) -> None:
    from PySide6.QtWidgets import QMessageBox

    answer = QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: answer))


def terms(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["terms"]


class TestTheMenuItem:
    def test_the_tray_offers_it(self, app):
        assert app.tray.apply_learned_action.text()

    def test_and_it_is_connected(self, app, paths, monkeypatch):
        _learned, words = paths
        agree(monkeypatch)
        app.tray.apply_learned_action.trigger()
        assert "کاربرد" in terms(words)


class TestAccepting:
    def test_the_forms_land_in_the_dictionary(self, app, paths, monkeypatch):
        _learned, words = paths
        agree(monkeypatch)
        app._apply_learned()
        assert terms(words)["کاربرد"] == ["کاربر"]
        assert terms(words)["kubectl"] == ["کیوب سی تی ال"]

    def test_saying_no_changes_nothing(self, app, paths, monkeypatch):
        _learned, words = paths
        agree(monkeypatch, yes=False)
        app._apply_learned()
        assert not words.exists()

    def test_the_suggestions_are_kept(self, app, paths, monkeypatch):
        # Deliberately not cleared: the file is also the record of what the
        # recogniser keeps getting wrong, and deleting it on accept would throw
        # that away for no reason.
        learned, _words = paths
        agree(monkeypatch)
        app._apply_learned()
        assert len(learning.load(learned)) == 2

    def test_what_was_already_there_survives(self, app, paths, monkeypatch):
        _learned, words = paths
        words.write_text(
            json.dumps({"terms": {"nginx": ["ان جین ایکس"]}}, ensure_ascii=False),
            encoding="utf-8",
        )
        agree(monkeypatch)
        app._apply_learned()
        assert terms(words)["nginx"] == ["ان جین ایکس"]
        assert "کاربرد" in terms(words)

    def test_applying_twice_does_not_duplicate(self, app, paths, monkeypatch):
        _learned, words = paths
        agree(monkeypatch)
        app._apply_learned()
        app._apply_learned()
        assert terms(words)["کاربرد"] == ["کاربر"]


class TestItTakesEffectNow:
    def test_the_lexicon_is_rebuilt_without_a_restart(self, app, paths, monkeypatch):
        # An entry that only works tomorrow is indistinguishable, from the
        # user's chair, from one that failed to save.
        agree(monkeypatch)
        before = len(app.lexicon)
        app._apply_learned()
        assert len(app.lexicon) > before

    def test_and_the_new_word_is_actually_produced(self, app, paths, monkeypatch):
        agree(monkeypatch)
        app._apply_learned()
        app.start_recording()
        app._on_result("کیوب سی تی ال", True)
        assert "kubectl" in app.overlay.text()


class TestABrokenDictionaryIsNeverOverwritten:
    def test_the_file_is_left_exactly_as_it_was(self, app, paths, monkeypatch):
        _learned, words = paths
        broken = '{"terms": {"nginx": ["ان جین ایکس"],}'  # trailing comma, unclosed
        words.write_text(broken, encoding="utf-8")
        agree(monkeypatch)
        app._apply_learned()
        assert words.read_text(encoding="utf-8") == broken

    def test_and_the_refusal_is_said_out_loud(self, app, paths, monkeypatch):
        _learned, words = paths
        words.write_text("{ not json", encoding="utf-8")
        said: list[str] = []
        monkeypatch.setattr(
            type(app.tray), "showMessage", lambda _s, _t, msg, *a, **k: said.append(msg)
        )
        agree(monkeypatch)
        app._apply_learned()
        assert said and "دست‌نخورده" in said[0]

    def test_a_terms_block_of_the_wrong_shape_is_refused_too(self, app, paths, monkeypatch):
        _learned, words = paths
        words.write_text('{"terms": []}', encoding="utf-8")
        agree(monkeypatch)
        with pytest.raises(learning.DictionaryUnreadable):
            learning.apply_to_dictionary(words, SUGGESTIONS)


class TestWithNothingLearnedYet:
    def test_it_says_so_instead_of_opening_a_dialog(self, app, monkeypatch, tmp_path):
        monkeypatch.setattr("mlqvoice.app.learned_file", lambda: tmp_path / "nothing.json")
        said: list[str] = []
        monkeypatch.setattr(
            type(app.tray), "showMessage", lambda _s, _t, msg, *a, **k: said.append(msg)
        )
        from PySide6.QtWidgets import QMessageBox

        def refuse(*_a, **_k):
            raise AssertionError("نباید پنجره‌ای باز شود وقتی چیزی برای افزودن نیست")

        monkeypatch.setattr(QMessageBox, "question", staticmethod(refuse))
        app._apply_learned()
        assert said and "یاد نگرفته" in said[0]


class TestTheSafeButtonIsTheDefault:
    def test_no_is_what_enter_would_press(self, app, paths, monkeypatch):
        # Same rule the panel learned the hard way: showing a dialog focused on
        # the action button means one stray Enter performs it.
        seen: list[object] = []

        from PySide6.QtWidgets import QMessageBox

        def spy(*args, **_kwargs):
            seen.append(args[-1])
            return QMessageBox.StandardButton.No

        monkeypatch.setattr(QMessageBox, "question", staticmethod(spy))
        app._apply_learned()
        assert seen == [QMessageBox.StandardButton.No]
