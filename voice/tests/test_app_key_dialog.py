"""Setting the key from the tray, and having it take effect on the spot.

Why this exists rather than "just use the command": the packaged app is
windowed and installed by a script, so reaching a shell that can see it is a
detour, and the one place the user is already looking is the tray menu.

The half that is easy to get wrong is not the dialog — it is what happens after
OK. Writing the key to disk and leaving the running app uncorrected looks
exactly like a key that does not work, and the only clue would be that
restarting fixes it.
"""

from __future__ import annotations

import json

import pytest

from mlqvoice.correct import mask


@pytest.fixture
def cfg_file(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr("mlqvoice.config.config_file", lambda: path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return path


def answer(monkeypatch, text: str, ok: bool = True) -> None:
    """Stand in for the input dialog, which cannot be shown in a test."""
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (text, ok)))


KEY = "AIzaSyTESTKEYtestkeyTESTKEY1234567890x"


class TestTheMenuItemIsThere:
    def test_the_tray_offers_it(self, app):
        assert app.tray.key_action.text()

    def test_and_it_is_wired_to_something(self, app, monkeypatch, cfg_file):
        # Not a formality: an action built and never connected shows up in the
        # menu, greys nothing out, and does nothing when clicked.
        answer(monkeypatch, KEY)
        app.tray.key_action.trigger()
        assert app.cfg.gemini_key == KEY


class TestItTakesEffectImmediately:
    def test_a_key_starts_the_worker_without_a_restart(self, app, monkeypatch, cfg_file):
        assert not app.correcting
        answer(monkeypatch, KEY)
        app._set_key()
        assert app.correcting
        assert app._corr_thread is not None

    def test_the_corrector_itself_gets_the_key(self, app, monkeypatch, cfg_file):
        # Starting the thread but leaving the corrector empty would mean every
        # sentence goes through a worker that returns it unchanged.
        answer(monkeypatch, KEY)
        app._set_key()
        assert app.corrector.api_key == KEY
        assert app.corrector.enabled

    def test_clearing_it_stops_the_worker(self, make_app, monkeypatch, cfg_file):
        voice = make_app(gemini_key=KEY)
        assert voice.correcting
        answer(monkeypatch, "   ")
        voice._set_key()
        assert not voice.correcting
        assert voice._corr_thread is None

    def test_cancelling_changes_nothing(self, make_app, monkeypatch, cfg_file):
        voice = make_app(gemini_key=KEY)
        answer(monkeypatch, "something else", ok=False)
        voice._set_key()
        assert voice.cfg.gemini_key == KEY


class TestItIsWrittenDown:
    def test_the_key_survives_the_next_start(self, app, monkeypatch, cfg_file):
        answer(monkeypatch, KEY)
        app._set_key()
        assert json.loads(cfg_file.read_text(encoding="utf-8"))["gemini_key"] == KEY

    def test_the_other_settings_survive_with_it(self, make_app, monkeypatch, cfg_file):
        voice = make_app(hotkey="ctrl+alt+f9")
        answer(monkeypatch, KEY)
        voice._set_key()
        assert json.loads(cfg_file.read_text(encoding="utf-8"))["hotkey"] == "ctrl+alt+f9"


class TestAPasteThatWentWrong:
    def test_quotes_around_it_are_stripped(self, app, monkeypatch, cfg_file):
        answer(monkeypatch, f'"{KEY}"')
        app._set_key()
        assert app.cfg.gemini_key == KEY

    def test_half_a_key_is_refused_rather_than_stored(self, app, monkeypatch, cfg_file):
        # A key with a space in it is almost always a selection that stopped
        # early. Storing it would fail later as an auth error, which points at
        # the wrong thing entirely.
        answer(monkeypatch, "AIza abc")
        app._set_key()
        assert app.cfg.gemini_key == ""
        assert not app.correcting

    def test_and_the_refusal_is_said_out_loud(self, app, monkeypatch, cfg_file):
        said: list[str] = []
        monkeypatch.setattr(
            type(app.tray), "showMessage", lambda _s, _t, msg, *a, **k: said.append(msg)
        )
        answer(monkeypatch, "AIza abc")
        app._set_key()
        assert said and "فاصله" in said[0]


class TestTheKeyIsNotShownBack:
    def test_the_confirmation_masks_it(self, app, monkeypatch, cfg_file):
        # This balloon can sit on screen while a screen is being shared.
        said: list[str] = []
        monkeypatch.setattr(
            type(app.tray), "showMessage", lambda _s, _t, msg, *a, **k: said.append(msg)
        )
        answer(monkeypatch, KEY)
        app._set_key()
        assert said
        assert KEY not in said[0]
        assert mask(KEY) in said[0]

    def test_and_the_prompt_does_not_repeat_it_either(self, make_app, monkeypatch, cfg_file):
        voice = make_app(gemini_key=KEY)
        shown: list[str] = []

        from PySide6.QtWidgets import QInputDialog

        def fake(_parent, _title, label, *a, **k):
            shown.append(label)
            return ("", False)

        monkeypatch.setattr(QInputDialog, "getText", staticmethod(fake))
        voice._set_key()
        assert shown
        assert KEY not in shown[0]


class TestASavedKeyThatStillDoesNothing:
    def test_says_why(self, make_app, monkeypatch, cfg_file):
        # correct=false in the config beats a key. Silence here reads as "I set
        # the key and it did not work".
        voice = make_app(correct=False)
        said: list[str] = []
        monkeypatch.setattr(
            type(voice.tray), "showMessage", lambda _s, _t, msg, *a, **k: said.append(msg)
        )
        answer(monkeypatch, KEY)
        voice._set_key()
        assert said and "correct=false" in said[0]
