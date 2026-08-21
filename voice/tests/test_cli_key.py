"""``mlqvoice key`` — setting the key without hand-editing JSON.

This command exists because the instructions were "open config.json in Notepad
and add a line". Asking anyone to write JSON by hand means a missing comma
turns into a parse error about the file, not a message about the thing they
were trying to do.

The other half of the file is about *not leaking the key*. It is printed by two
commands, and command output is exactly what somebody pastes into a chat when
they are stuck — so it is masked, and there are tests to keep it masked.
"""

from __future__ import annotations

import json

import pytest

from mlqvoice.__main__ import main
from mlqvoice.correct import ENV_KEY, mask, resolve_key

KEY = "AIzaSyTESTKEYtestkeyTESTKEY1234567890x"


@pytest.fixture
def cfg_path(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr("mlqvoice.config.config_file", lambda: path)
    monkeypatch.setattr("mlqvoice.__main__.config_file", lambda: path)
    monkeypatch.delenv(ENV_KEY, raising=False)
    return path


def stored(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestSettingIt:
    def test_a_key_is_written_to_the_config(self, cfg_path, capsys):
        assert main(["key", KEY]) == 0
        assert stored(cfg_path)["gemini_key"] == KEY

    def test_the_other_settings_survive(self, cfg_path):
        # Written by rewriting the whole file, so this is worth pinning: losing
        # someone's hotkey to set a key would be a rotten trade.
        main(["key", KEY])
        data = stored(cfg_path)
        assert data["hotkey"] == "alt+space"
        assert data["lang"] == "fa-IR"

    def test_quotes_around_a_pasted_key_are_stripped(self, cfg_path):
        main(["key", f'"{KEY}"'])
        assert stored(cfg_path)["gemini_key"] == KEY

    def test_a_key_equals_prefix_is_stripped(self, cfg_path):
        main(["key", f"key={KEY}"])
        assert stored(cfg_path)["gemini_key"] == KEY

    def test_a_key_with_a_space_is_refused(self, cfg_path, capsys):
        # Almost always a half-copied paste. Storing it would fail later as an
        # auth error, which says nothing about what went wrong.
        assert main(["key", "AIza abc"]) == 1
        assert not cfg_path.exists() or not stored(cfg_path)["gemini_key"]

    def test_an_empty_key_is_refused(self, cfg_path):
        assert main(["key", "   "]) == 1


class TestShowingIt:
    def test_with_no_key_it_says_how_to_get_one(self, cfg_path, capsys):
        assert main(["key"]) == 0
        out = capsys.readouterr().out
        assert "aistudio.google.com" in out

    def test_a_set_key_is_shown_masked_never_whole(self, cfg_path, capsys):
        main(["key", KEY])
        capsys.readouterr()
        assert main(["key"]) == 0
        out = capsys.readouterr().out
        assert KEY not in out
        assert mask(KEY) in out

    def test_check_shows_the_state_without_the_key(self, cfg_path, capsys):
        main(["key", KEY])
        capsys.readouterr()
        assert main(["check"]) == 0
        out = capsys.readouterr().out
        assert KEY not in out
        assert "روشن" in out

    def test_check_says_so_when_no_key_is_set(self, cfg_path, capsys):
        assert main(["check"]) == 0
        assert "خاموش" in capsys.readouterr().out

    def test_setting_it_does_not_echo_the_whole_key(self, cfg_path, capsys):
        main(["key", KEY])
        assert KEY not in capsys.readouterr().out


class TestClearingIt:
    def test_the_key_is_removed(self, cfg_path):
        main(["key", KEY])
        assert main(["key", "--clear"]) == 0
        assert stored(cfg_path)["gemini_key"] == ""

    def test_and_it_warns_when_the_environment_still_has_one(self, cfg_path, monkeypatch, capsys):
        # Otherwise "I cleared it and it is still correcting" is a mystery.
        main(["key", KEY])
        monkeypatch.setenv(ENV_KEY, KEY)
        capsys.readouterr()
        main(["key", "--clear"])
        assert ENV_KEY in capsys.readouterr().err


class TestWhereTheKeyComesFrom:
    def test_the_config_file_wins_over_the_environment(self, monkeypatch):
        # The file is the choice someone made on purpose; a variable inherited
        # from another tool must not silently override it.
        monkeypatch.setenv(ENV_KEY, "from-env")
        assert resolve_key("from-file") == "from-file"

    def test_the_environment_is_used_when_the_file_has_none(self, monkeypatch):
        monkeypatch.setenv(ENV_KEY, "from-env")
        assert resolve_key("") == "from-env"

    def test_neither_means_no_key(self, monkeypatch):
        monkeypatch.delenv(ENV_KEY, raising=False)
        assert resolve_key("") == ""

    def test_surrounding_whitespace_never_survives(self, monkeypatch):
        monkeypatch.delenv(ENV_KEY, raising=False)
        assert resolve_key("  abc  ") == "abc"


class TestTheMask:
    def test_it_keeps_enough_to_recognise(self):
        assert mask(KEY).startswith("AIza")
        assert mask(KEY).endswith(KEY[-4:])

    def test_it_never_shows_the_middle(self):
        assert KEY[8:-8] not in mask(KEY)

    def test_a_short_string_gives_nothing_away(self):
        # Under thirteen characters, first-four-plus-last-four would be most of
        # it — so nothing is shown at all.
        assert mask("short") == "…"

    def test_no_key_reads_as_no_key(self):
        assert mask("") == "—"
        assert mask("   ") == "—"
