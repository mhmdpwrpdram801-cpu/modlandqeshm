import json

import pytest

from mlqvoice.config import Config, ConfigError, from_dict, load, parse_hotkey, save


class TestHotkey:
    def test_default_parses(self):
        hk = parse_hotkey("ctrl+alt+space")
        assert hk.modifiers == 0x0002 | 0x0001
        assert hk.vk == 0x20
        assert str(hk) == "ctrl+alt+space"

    def test_case_and_spacing_are_forgiving(self):
        assert parse_hotkey(" Ctrl + Alt + Space ").vk == parse_hotkey("ctrl+alt+space").vk

    def test_control_is_an_alias_for_ctrl(self):
        assert parse_hotkey("control+f9").modifiers == parse_hotkey("ctrl+f9").modifiers

    def test_function_key_needs_no_modifier(self):
        assert parse_hotkey("f9").vk == 0x78

    def test_bare_letter_is_rejected(self):
        # Grabbing "a" globally would break typing in every application.
        with pytest.raises(ConfigError, match="hotkey"):
            parse_hotkey("a")

    def test_letter_with_modifier_is_fine(self):
        assert parse_hotkey("ctrl+shift+d").vk == ord("D")

    def test_modifiers_only_is_rejected(self):
        with pytest.raises(ConfigError, match="کلیدِ اصلی"):
            parse_hotkey("ctrl+alt")

    def test_two_main_keys_is_rejected(self):
        with pytest.raises(ConfigError, match="بیش از یک"):
            parse_hotkey("ctrl+a+b")

    def test_unknown_key_names_itself_in_the_error(self):
        with pytest.raises(ConfigError, match="banana"):
            parse_hotkey("ctrl+banana")

    def test_empty(self):
        with pytest.raises(ConfigError):
            parse_hotkey("   ")


class TestValidate:
    def test_defaults_are_valid(self):
        assert Config().validate().vk == 0x20

    def test_the_default_hotkey_is_alt_space(self):
        hk = Config().validate()
        assert str(hk) == "alt+space"
        assert hk.modifiers == 0x0001  # MOD_ALT only

    def test_bad_digits_mode(self):
        with pytest.raises(ConfigError, match="digits"):
            Config(digits="roman").validate()

    def test_bad_insert_mode(self):
        with pytest.raises(ConfigError, match="insert_mode"):
            Config(insert_mode="telepathy").validate()

    def test_port_out_of_range(self):
        with pytest.raises(ConfigError, match="port"):
            Config(port=70000).validate()

    def test_empty_lang(self):
        with pytest.raises(ConfigError, match="lang"):
            Config(lang="  ").validate()

    def test_negative_silence_timeout(self):
        with pytest.raises(ConfigError, match="auto_stop_seconds"):
            Config(auto_stop_seconds=-1).validate()

    def test_zero_silence_timeout_is_allowed(self):
        # It is how you turn the feature off, not a mistake.
        assert Config(auto_stop_seconds=0).validate()

    def test_an_absurd_silence_timeout(self):
        with pytest.raises(ConfigError, match="auto_stop_seconds"):
            Config(auto_stop_seconds=99999).validate()

    def test_a_number_written_as_text_names_the_field(self):
        # The file is hand-edited, so quoting a number is an easy slip. Comparing
        # a string against an int raises TypeError, which used to escape as a
        # traceback with no clue which setting caused it.
        with pytest.raises(ConfigError, match="auto_stop_seconds"):
            Config(auto_stop_seconds="4").validate()

    def test_and_so_does_a_quoted_port(self):
        with pytest.raises(ConfigError, match="port"):
            Config(port="8080").validate()

    def test_true_is_not_a_number(self):
        # bool is an int subclass, so `0 <= True <= 600` passes happily and the
        # timer would silently become one millisecond.
        with pytest.raises(ConfigError, match="auto_stop_seconds"):
            Config(auto_stop_seconds=True).validate()

    def test_missing_browser_path_is_reported_not_ignored(self, tmp_path):
        with pytest.raises(ConfigError, match="browser_path"):
            Config(browser_path=str(tmp_path / "nope.exe")).validate()

    def test_existing_browser_path_passes(self, tmp_path):
        exe = tmp_path / "chrome.exe"
        exe.write_text("")
        Config(browser_path=str(exe)).validate()


class TestLoadSave:
    def test_missing_file_gives_defaults(self, tmp_path):
        assert load(tmp_path / "none.json") == Config()

    def test_media_pause_is_on_by_default(self, tmp_path):
        assert Config().pause_media

    def test_the_silence_timeout_has_a_sane_default(self, tmp_path):
        assert Config().auto_stop_seconds == 4

    def test_round_trip(self, tmp_path):
        path = tmp_path / "config.json"
        cfg = Config(hotkey="ctrl+shift+v", digits="fa", interim=False)
        save(cfg, path)
        assert load(path) == cfg

    def test_partial_file_keeps_defaults_for_the_rest(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"hotkey": "f9"}), encoding="utf-8")
        cfg = load(path)
        assert cfg.hotkey == "f9"
        assert cfg.digits == "latin"

    def test_unknown_keys_are_kept_for_reporting_not_crashed_on(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"hotkey": "f9", "colour": "blue"}), encoding="utf-8")
        assert load(path)._unknown == ("colour",)

    def test_broken_json_names_the_file(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{ nope", encoding="utf-8")
        with pytest.raises(ConfigError, match=r"config\.json"):
            load(path)

    def test_json_that_is_not_an_object(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(ConfigError, match="شیء JSON"):
            load(path)

    def test_saved_file_is_readable_persian(self, tmp_path):
        path = tmp_path / "config.json"
        save(Config(), path)
        assert "\\u" not in path.read_text(encoding="utf-8")

    def test_unknown_marker_is_not_written_back_to_disk(self, tmp_path):
        path = tmp_path / "config.json"
        save(from_dict({"colour": "blue"}), path)
        assert "_unknown" not in path.read_text(encoding="utf-8")
