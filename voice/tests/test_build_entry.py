"""The entry point PyInstaller is given must work as a bare script.

Regression: build.ps1 used to point PyInstaller at ``src/mlqvoice/__main__.py``.
Running a module of a package as a top-level script strips its package context,
so every ``from . import ...`` inside it raises — the exe would have died on
launch, and nothing in the test suite noticed because the tests import the
package properly.
"""

import subprocess
import sys
from pathlib import Path

VOICE = Path(__file__).resolve().parent.parent
LAUNCHER = VOICE / "scripts" / "launcher.py"


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        "PYTHONPATH": str(VOICE / "src"),
        "PATH": "/usr/bin:/bin",
        "QT_QPA_PLATFORM": "offscreen",
        "HOME": str(Path.home()),
    }
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


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
