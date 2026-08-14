import pytest

from mlqvoice.__main__ import main


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    """Keep the tests off the real config and dictionary."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))


class TestSay:
    def test_words_from_the_command_line(self, capsys):
        assert main(["say", "کامیت", "کن", "نقطه"]) == 0
        assert capsys.readouterr().out.strip() == "commit کن."

    def test_reads_stdin_when_given_no_words(self, capsys, monkeypatch):
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO("دیتابیس"))
        assert main(["say"]) == 0
        assert capsys.readouterr().out.strip() == "database"

    def test_picks_up_the_user_dictionary(self, capsys, tmp_path):
        (tmp_path / "mlqvoice").mkdir(parents=True, exist_ok=True)
        (tmp_path / "mlqvoice" / "dictionary.json").write_text(
            '{"terms": {"kubectl": ["کیوب سی تی ال"]}}', encoding="utf-8"
        )
        assert main(["say", "کیوب", "سی", "تی", "ال"]) == 0
        assert capsys.readouterr().out.strip() == "kubectl"


class TestCheck:
    def test_reports_the_defaults(self, capsys):
        assert main(["check"]) == 0
        out = capsys.readouterr().out
        assert "alt+space" in out  # the default
        assert "fa-IR" in out

    def test_fails_on_a_broken_config(self, capsys, tmp_path):
        (tmp_path / "mlqvoice").mkdir(parents=True, exist_ok=True)
        (tmp_path / "mlqvoice" / "config.json").write_text('{"digits": "roman"}', encoding="utf-8")
        assert main(["check"]) == 1
        assert "digits" in capsys.readouterr().err


class TestHotkeyCommand:
    def test_valid(self, capsys):
        assert main(["hotkey", "ctrl+alt+space"]) == 0
        assert "vk=0x20" in capsys.readouterr().out

    def test_invalid_returns_nonzero(self, capsys):
        assert main(["hotkey", "ctrl+banana"]) == 1
        assert "banana" in capsys.readouterr().err


class TestPaths:
    def test_prints_all_three(self, capsys):
        assert main(["paths"]) == 0
        out = capsys.readouterr().out
        assert "config.json" in out
        assert "dictionary.json" in out


class TestVersion:
    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        assert "mlqvoice" in capsys.readouterr().out


class TestSelftest:
    """Guards the exe smoke test: selftest must build the real UI chain."""

    def test_builds_the_ui_and_reports_ok(self, capsys):
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        pytest.importorskip("PySide6", reason="PySide6 نصب نیست")
        assert main(["selftest"]) == 0
        out = capsys.readouterr().out
        assert "selftest ok" in out
        assert "واژه‌ها=" in out
