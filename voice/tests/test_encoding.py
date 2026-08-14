"""Persian output must survive a non-UTF-8 console.

Found by the first CI run on a real Windows machine: Python picks the process
ANSI code page for stdout — cp1252 on a US Windows install — and the very first
Persian line of ``check`` died with UnicodeEncodeError.  Every subcommand here
prints Persian, so this affected all of them.

These reproduce it anywhere by forcing the same encoding through
``PYTHONIOENCODING``; they fail without :func:`mlqvoice.__main__.force_utf8`.
"""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

VOICE = Path(__file__).resolve().parent.parent

# cp1252 is what a US Windows install gives you; cp1256 is the Persian/Arabic
# one an Iranian Windows is likely to be on. Neither can carry this text.
LEGACY_CODEPAGES = ["cp1252", "cp1256", "ascii"]


def run_cli(*args: str, encoding: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PYTHONPATH": str(VOICE / "src"),
        "PYTHONIOENCODING": encoding,
        "QT_QPA_PLATFORM": "offscreen",
    }
    return subprocess.run(
        [sys.executable, "-m", "mlqvoice", *args],
        capture_output=True,
        # Decode as UTF-8 explicitly rather than with text=True. text=True uses
        # the *parent's* locale encoding — cp1252 on Windows — and the child now
        # correctly emits UTF-8, so the reader thread died with UnicodeDecodeError
        # and left stdout/stderr as None. The child ignores PYTHONIOENCODING here
        # precisely because force_utf8 overrides it; that is what is under test.
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
        check=False,
    )


class TestLegacyCodepages:
    @pytest.mark.parametrize("encoding", LEGACY_CODEPAGES)
    def test_check_does_not_crash(self, encoding):
        result = run_cli("check", encoding=encoding)
        assert "UnicodeEncodeError" not in result.stderr
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("encoding", LEGACY_CODEPAGES)
    def test_paths_does_not_crash(self, encoding):
        result = run_cli("paths", encoding=encoding)
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("encoding", LEGACY_CODEPAGES)
    def test_say_does_not_crash_on_persian_output(self, encoding):
        # "سلام" has no glossary entry, so it comes back out in Persian — the
        # case where the output itself is what the console cannot encode.
        result = run_cli("say", "سلام", "دنیا", encoding=encoding)
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("encoding", LEGACY_CODEPAGES)
    def test_a_persian_error_message_does_not_crash(self, encoding):
        result = run_cli("hotkey", "ctrl+banana", encoding=encoding)
        assert result.returncode == 1  # the error itself, not an encoding crash
        assert "UnicodeEncodeError" not in result.stderr

    def test_utf8_still_prints_the_real_text(self):
        result = run_cli("check", encoding="utf-8")
        assert result.returncode == 0
        assert "کلیدِ میان‌بُر" in result.stdout

    @pytest.mark.parametrize("encoding", LEGACY_CODEPAGES)
    def test_the_bytes_on_stdout_are_utf8_whatever_the_console_claims(self, encoding):
        """The real invariant, asserted on raw bytes.

        Checking decoded text can be masked by whatever the *parent* happens to
        decode with — which is exactly how the CI failure after the first fix
        looked like an app bug when it was a harness bug.  Reading the bytes
        cannot be fooled by either side's locale.
        """
        env = {
            **os.environ,
            "PYTHONPATH": str(VOICE / "src"),
            "PYTHONIOENCODING": encoding,
        }
        result = subprocess.run(
            [sys.executable, "-m", "mlqvoice", "check"],
            capture_output=True,  # bytes: no text=, no encoding=
            timeout=120,
            env=env,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "کلیدِ میان‌بُر" in result.stdout.decode("utf-8")


class TestForceUtf8:
    def test_reconfigures_a_legacy_stream(self):
        from mlqvoice.__main__ import force_utf8

        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        original = sys.stdout
        sys.stdout = stream
        try:
            force_utf8()
            assert sys.stdout.encoding.lower().replace("-", "") == "utf8"
            sys.stdout.write("کلیدِ میان‌بُر")  # would have raised on cp1252
        finally:
            sys.stdout = original

    def test_survives_a_stream_without_reconfigure(self):
        from mlqvoice.__main__ import force_utf8

        class Dumb:
            def write(self, _s):
                return 0

        original = sys.stdout
        sys.stdout = Dumb()
        try:
            force_utf8()  # must not raise
        finally:
            sys.stdout = original

    def test_survives_a_missing_stream(self):
        from mlqvoice.__main__ import force_utf8

        original = sys.stdout
        sys.stdout = None
        try:
            force_utf8()  # the --windowed exe case
        finally:
            sys.stdout = original
