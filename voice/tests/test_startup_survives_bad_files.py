"""A hand-edited file must never make the app vanish.

The tray menu invites the user to open `dictionary.json` in Notepad, so a
trailing comma in it is not an exotic accident — it is Tuesday. Until this
file existed, that comma raised ``JSONDecodeError`` out of ``VoiceApp``'s
constructor, ``run()`` caught only three unrelated types, and a ``--windowed``
build died with **no window and no message**. Double-click, nothing happens,
no way to find out why.

``config.json`` was already handled properly. The dictionary — the one file we
actively ask people to edit — was not.

Three shapes of breakage are covered because they fail in three different
places: bad JSON, a symbol missing its ``text``, and an ``attach`` value the
loader does not know.
"""

from __future__ import annotations

import json

import pytest

from mlqvoice.text.lexicon import DictionaryError, build_lexicon, spoken_key

BROKEN = {
    "trailing comma": '{"terms": {"kubectl": ["کیوب سی تی ال"],}}',
    "not json at all": "{ nope",
    "symbol with no text": json.dumps({"symbols": [{"say": ["تیلدا"]}]}, ensure_ascii=False),
    "unknown attach": json.dumps(
        {"symbols": [{"say": ["تیلدا"], "text": "~", "attach": "chap"}]}, ensure_ascii=False
    ),
    "terms is a list": json.dumps({"terms": ["kubectl"]}),
    "spoken forms are a number": json.dumps({"terms": {"kubectl": 7}}),
}


@pytest.mark.parametrize("shape", list(BROKEN))
def test_every_shape_of_breakage_is_one_recognisable_error(shape, tmp_path):
    path = tmp_path / "dictionary.json"
    path.write_text(BROKEN[shape], encoding="utf-8")
    with pytest.raises(DictionaryError):
        build_lexicon(user_file=path)


@pytest.mark.parametrize("shape", list(BROKEN))
def test_and_the_message_names_the_file(shape, tmp_path):
    # "JSONDecodeError: line 1 column 34" tells someone nothing about *which*
    # of their files is unhappy. The path is the whole point of the message.
    path = tmp_path / "dictionary.json"
    path.write_text(BROKEN[shape], encoding="utf-8")
    with pytest.raises(DictionaryError, match=r"dictionary\.json"):
        build_lexicon(user_file=path)


class TestTheAppSurvivesIt:
    def test_run_catches_it_instead_of_dying(self, monkeypatch, tmp_path):
        """The real guard: `run()` must show a message, not disappear."""
        from mlqvoice import app as app_mod

        path = tmp_path / "dictionary.json"
        path.write_text(BROKEN["trailing comma"], encoding="utf-8")
        monkeypatch.setattr(app_mod, "user_dictionary_file", lambda: path)
        monkeypatch.setattr(app_mod, "config_file", lambda: tmp_path / "config.json")
        monkeypatch.setattr(app_mod, "IS_WINDOWS", True)

        shown: list[str] = []
        monkeypatch.setattr(
            app_mod.QMessageBox, "critical", staticmethod(lambda *a: shown.append(a[-1]))
        )
        monkeypatch.setattr(app_mod.QApplication, "exec", lambda _self: 0)

        code = app_mod.run()
        assert code == 2
        assert shown, "برنامه بی‌صدا مرد — هیچ پیامی به کاربر نرسید"
        assert "dictionary.json" in shown[0]
        # And it arrives as *itself*, not wrapped in the last-resort handler.
        # Without this line the typed branch is dead weight: the catch-all below
        # it would produce a message containing the path too, and the check
        # would pass with the specific case removed. A failure we anticipated
        # should read like one.
        assert "راه‌اندازی شکست خورد" not in shown[0]

    def test_a_healthy_dictionary_still_loads(self, tmp_path):
        # Half the value of the check above is this one: it must not have been
        # bought by refusing files that are perfectly fine.
        path = tmp_path / "dictionary.json"
        path.write_text(
            json.dumps({"terms": {"kubectl": ["کیوب سی تی ال"]}}, ensure_ascii=False),
            encoding="utf-8",
        )
        lex = build_lexicon(user_file=path)
        assert lex.get(spoken_key("کیوب سی تی ال")) is not None

    def test_a_missing_dictionary_is_normal_and_silent(self, tmp_path):
        build_lexicon(user_file=tmp_path / "not-there.json")


class TestNothingElseDiesQuietlyEither:
    def test_an_unexpected_failure_at_startup_still_says_something(self, monkeypatch, tmp_path):
        """A windowed build with no console has exactly one way to speak.

        Whatever goes wrong while the app is being built, vanishing is never an
        acceptable answer — the user is left with an icon that does nothing and
        no thread to pull.
        """
        from mlqvoice import app as app_mod

        monkeypatch.setattr(app_mod, "config_file", lambda: tmp_path / "config.json")
        monkeypatch.setattr(app_mod, "IS_WINDOWS", True)

        def explode(_cfg):
            raise RuntimeError("چیزی که هیچ‌کس پیش‌بینی نکرده بود")

        monkeypatch.setattr(app_mod, "VoiceApp", explode)
        shown: list[str] = []
        monkeypatch.setattr(
            app_mod.QMessageBox, "critical", staticmethod(lambda *a: shown.append(a[-1]))
        )

        assert app_mod.run() == 2
        assert shown and "پیش‌بینی نکرده" in shown[0]
