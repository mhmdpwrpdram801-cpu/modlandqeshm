"""The entry point PyInstaller is given must work as a bare script.

Regression: build.ps1 used to point PyInstaller at ``src/mlqvoice/__main__.py``.
Running a module of a package as a top-level script strips its package context,
so every ``from . import ...`` inside it raises — the exe would have died on
launch, and nothing in the test suite noticed because the tests import the
package properly.
"""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

VOICE = Path(__file__).resolve().parent.parent
LAUNCHER = VOICE / "scripts" / "launcher.py"


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    # Inherit the real environment and only add what we need.  Handing Windows a
    # hand-built env without SYSTEMROOT stops Python from starting at all, so a
    # from-scratch dict would fail here for reasons that have nothing to do with
    # what is being tested.
    env = {
        **os.environ,
        "PYTHONPATH": str(VOICE / "src"),
        "QT_QPA_PLATFORM": "offscreen",
    }
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


class TestWindowedStreams:
    """A --windowed build has sys.stdout is None; nothing may crash on that."""

    def test_ensure_streams_replaces_a_missing_stdout(self, monkeypatch):
        sys.path.insert(0, str(VOICE / "scripts"))
        import launcher

        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        launcher.ensure_streams()
        assert sys.stdout is not None
        assert sys.stderr is not None
        print("this would have raised AttributeError before")  # the actual failure mode

    def test_existing_streams_are_left_alone(self, monkeypatch):
        sys.path.insert(0, str(VOICE / "scripts"))
        import launcher

        sentinel = io.StringIO()
        monkeypatch.setattr(sys, "stdout", sentinel)
        launcher.ensure_streams()
        assert sys.stdout is sentinel

    def test_attach_parent_console_is_a_noop_off_windows(self):
        sys.path.insert(0, str(VOICE / "scripts"))
        import launcher

        if sys.platform == "win32":
            pytest.skip("این تست برای بیرونِ ویندوز است")
        assert launcher.attach_parent_console() is False


class TestLauncher:
    def test_exists_where_build_ps1_looks_for_it(self):
        assert LAUNCHER.exists()
        build = (VOICE / "scripts" / "build.ps1").read_text(encoding="utf-8")
        assert "scripts/launcher.py" in build

    def test_runs_as_a_bare_script(self):
        result = run(LAUNCHER, "check")
        assert result.returncode == 0, result.stderr
        assert "mlqvoice" in result.stdout

    def test_the_package_main_is_reachable_through_it(self):
        result = run(LAUNCHER, "say", "کامیت")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "commit"

    def test_running_the_package_module_as_a_script_is_what_breaks(self):
        # Documents *why* the launcher exists; if this ever starts passing, the
        # launcher is no longer load-bearing and the indirection can go.
        result = run(VOICE / "src" / "mlqvoice" / "__main__.py", "check")
        assert result.returncode != 0
        assert "relative import" in result.stderr
