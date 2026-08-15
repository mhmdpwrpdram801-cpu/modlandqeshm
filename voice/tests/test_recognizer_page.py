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

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SIM = Path(__file__).parent / "recsim" / "run.mjs"


def _show(raw: bytes) -> None:
    """Put the simulator's own report in the log, in bytes.

    Not ``print``: the report is in Persian, and Windows hands a test process a
    cp1252 stdout — the first version of this file died with UnicodeEncodeError
    while the thing it was reporting on had passed 13/13. The app already learned
    this lesson once (``force_utf8`` in ``__main__``); a test may not quietly
    forget it. GitHub's log is UTF-8, so raw bytes come out right.
    """
    sys.stdout.buffer.write(b"\n" + raw)
    sys.stdout.buffer.flush()


def test_the_simulator_is_shipped():
    assert SIM.exists(), f"شبیه‌ساز پیدا نشد: {SIM}"


def test_node_is_available():
    """Deliberately a failure, not a skip.

    A gate that cannot run has not passed (CORE-12). Skipping here would turn a
    missing tool into a green tick, and the page would go unchecked exactly when
    nobody notices.
    """
    assert shutil.which("node"), "node نصب نیست — بررسی‌های صفحه‌ی تشخیص اجرا نشدند"


def test_the_page_behaves():
    # Bytes throughout, decoded explicitly: text=True would decode with the
    # parent's locale, which on Windows is not UTF-8. That exact mistake once
    # sent this project chasing a phantom encoding bug in the app itself.
    proc = subprocess.run(["node", str(SIM)], capture_output=True, timeout=60)
    report = proc.stdout.decode("utf-8", "replace")

    if proc.returncode != 0:
        _show(proc.stdout + proc.stderr)
        # ASCII-only message: this string reaches the terminal writer directly,
        # and a failure report that cannot be printed is not a failure report.
        failures = report.count("❌")
        pytest.fail(f"recsim: {failures} check(s) failed, exit {proc.returncode} (report above)")

    passed = re.search(r"(\d+)/(\d+)", report)
    assert passed, f"recsim printed no tally:\n{report}"
    assert passed.group(1) == passed.group(2), f"recsim: only {passed.group(0)} passed"


def test_the_simulator_reads_the_file_that_ships():
    # If the sim ever pointed at a fixture, every check above would become
    # decoration. This asserts the path it opens is the packaged page.
    from mlqvoice.bridge import RecognizerBridge

    referenced = SIM.read_text(encoding="utf-8")
    assert '"web", "recognizer.html"' in referenced
    assert "webkitSpeechRecognition" in RecognizerBridge().page_html()
