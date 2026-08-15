"""The recogniser page, run rather than read.

Everything else in this suite is Python. The page is not: it is JavaScript that
only ever executes inside the user's Chrome, which is precisely why a retry loop
could sit in it unnoticed — no test could reach it, and the window it runs in is
positioned off-screen where its error banner is invisible.

So the JS gets its own simulator (``tests/recsim/run.mjs``), and this hands it to
the pytest gate. It runs the shipped file, not a copy: a check against a rewrite
would pass happily while the page users actually get stays broken.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SIM = Path(__file__).parent / "recsim" / "run.mjs"


def test_the_simulator_is_shipped():
    assert SIM.exists(), f"شبیه‌ساز پیدا نشد: {SIM}"


def test_node_is_available():
    """Deliberately a failure, not a skip.

    A gate that cannot run has not passed (CORE-12). Skipping here would turn a
    missing tool into a green tick, and the page would go unchecked exactly when
    nobody notices.
    """
    assert shutil.which("node"), "node نصب نیست — بررسی‌های صفحه‌ی تشخیص اجرا نشدند"


def test_the_page_behaves(capsys):
    proc = subprocess.run(
        ["node", str(SIM)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    with capsys.disabled():
        print("\n" + proc.stdout.rstrip())
    if proc.returncode != 0:
        pytest.fail(f"بررسی‌های صفحه‌ی تشخیص افتادند:\n{proc.stdout}\n{proc.stderr}")


def test_the_simulator_reads_the_file_that_ships():
    # If the sim ever pointed at a fixture, every check above would become
    # decoration. This asserts the path it opens is the packaged page.
    from mlqvoice.bridge import RecognizerBridge

    referenced = SIM.read_text(encoding="utf-8")
    assert '"web", "recognizer.html"' in referenced
    assert "webkitSpeechRecognition" in RecognizerBridge().page_html()
