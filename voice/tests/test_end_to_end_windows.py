"""The whole journey, with real windows and real keystrokes — no microphone.

Everything else in the suite runs offscreen and drives Qt directly. That proves
the logic, and it is what caught most bugs, but it cannot answer the question
the owner actually asked: *when I type, does Persian appear, and does "تمام شد"
put it in my window?* Between the keyboard and that outcome sit three things no
offscreen test touches — the OS keyboard queue, window focus, and the clipboard.

So this file uses none of the shortcuts:

* real visible windows (``QT_QPA_PLATFORM`` deliberately unset),
* keys delivered through ``SendInput``, the same call the OS uses for a real
  keyboard, aimed at whatever window has focus rather than at a widget,
* a destination that is a **separate process**, so the focus hand-off is real.

It is opt-in through ``MLQ_E2E`` because it cannot share a process with the
offscreen tests: ``QApplication`` picks its platform once, and by the time any
other test file has run, that choice is made. The Windows workflow runs it as
its own step — if that step ever disappears, this file stops running and
nothing else will notice.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="مسیرِ Win32 فقط روی ویندوز"),
    pytest.mark.skipif(
        os.environ.get("MLQ_E2E") != "1",
        reason="پنجره‌ی واقعی لازم دارد — با MLQ_E2E=1 و بدونِ QT_QPA_PLATFORM اجرا می‌شود",
    ),
]

if os.environ.get("MLQ_E2E") == "1":
    # Clearing this in the workflow is not enough, and the first run proved it:
    # ``conftest.py`` sets it from *inside* the process, before this module is
    # imported, so the step arrived with an empty environment and Qt still went
    # offscreen. Undo it here, where the requirement actually lives — and only
    # under the opt-in, because this module is still imported (and skipped)
    # during ordinary runs, where every other file does need offscreen.
    os.environ.pop("QT_QPA_PLATFORM", None)

if os.name == "nt" and os.environ.get("MLQ_E2E") == "1":
    from PySide6.QtWidgets import QApplication

    from mlqvoice import inject
    from mlqvoice.text import build_lexicon, finglish_to_persian
    from mlqvoice.ui.overlay import Overlay
    from mlqvoice.win32 import (
        KEYEVENTF_KEYUP,
        VK_CONTROL,
        VK_RETURN,
        key_input,
        send_input,
        unicode_inputs,
        user32,
    )

TARGET = Path(__file__).parent / "target_window.py"


def pump(app, seconds: float = 0.35) -> None:
    """Let Qt catch up with the keys the OS just delivered."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def type_keys(app, text: str) -> None:
    """Type *text* the way a keyboard does, one character at a time."""
    for ch in text:
        send_input(unicode_inputs(ch))
        pump(app, 0.05)


@pytest.fixture(scope="module")
def qt_app():
    # Guards the premise, and asks Qt rather than the environment: the variable
    # is only how the platform gets chosen, `platformName()` is what was
    # actually chosen. An offscreen QApplication would make every assertion
    # below meaningless while still letting some of them pass, which is the
    # worst way for this file to fail.
    app = QApplication.instance() or QApplication([])
    assert app.platformName() != "offscreen", (
        f"پلتفرمِ Qt «{app.platformName()}» است — بدونِ پنجره‌ی واقعی، "
        "کلیدهای SendInput به جایی نمی‌رسند و نتیجه‌ی این فایل بی‌معنی است"
    )
    return app


@pytest.fixture
def target(tmp_path):
    """A second program to write into, exactly like the user's editor."""
    path = tmp_path / "typed.txt"
    proc = subprocess.Popen([sys.executable, str(TARGET), str(path)])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"پنجره‌ی هدف بالا نیامد — کدِ {proc.returncode}")
        if path.exists():
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("پنجره‌ی هدف ظاهر نشد")
    hwnd = _find_window(proc.pid)
    try:
        yield _Target(proc, path, hwnd)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _find_window(pid: int) -> int:
    import ctypes
    from ctypes import wintypes

    found: list[int] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _l):
        owner = wintypes.DWORD(0)
        user32().GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32().IsWindowVisible(hwnd):
            found.append(int(hwnd))
        return True

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        user32().EnumWindows(proto(visit), 0)
        if found:
            return found[0]
        time.sleep(0.1)
    pytest.fail("پنجره‌ی هدف هندل نگرفت")


class _Target:
    def __init__(self, proc, path, hwnd):
        self.proc, self.path, self.hwnd = proc, path, hwnd

    def text(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def wait_for(self, expected: str, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.text() == expected:
                return True
            time.sleep(0.05)
        return False


def focus_box(app, overlay) -> None:
    """Put the keyboard back on the box, and say who had it if that fails.

    Anything that opens a window takes the foreground with it, so this has to be
    re-asserted rather than done once. The first version of these tests learned
    that the hard way: the destination window opened *after* the box, quietly
    took the focus, and every keystroke meant for the box went into it — which
    surfaced as "Ctrl+Enter sent nothing" and said nothing about why.
    """
    assert inject.focus_window(int(overlay.winId())), (
        "کادر فوکوس نگرفت — فوکوس دستِ: "
        f"{inject.window_title(int(user32().GetForegroundWindow()))!r}"
    )
    overlay._text.setFocus()
    pump(app, 0.2)


@pytest.fixture
def box(qt_app):
    """The dictation box, live and focusable, with the real dictionary."""
    skip = build_lexicon().outputs()
    overlay = Overlay()
    overlay.set_transliterator(lambda w: finglish_to_persian(w, skip=skip))
    overlay.begin_session()
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()
    pump(qt_app, 0.6)
    focus_box(qt_app, overlay)
    try:
        yield overlay
    finally:
        overlay.close()
        overlay.deleteLater()
        pump(qt_app, 0.1)


class TestTypingFinglishGivesPersian:
    """The owner's words: «هر حروف انگلیسی زدم همینو دقیقا به فارسی تبدیل کنه»."""

    def test_a_word_becomes_persian_when_it_ends(self, qt_app, box):
        type_keys(qt_app, "salam ")
        pump(qt_app)
        assert box.text().strip() == "سلام", f"چیزی که در کادر است: {box.text()!r}"

    def test_a_whole_sentence_converts_word_by_word(self, qt_app, box):
        type_keys(qt_app, "salam chetori ")
        pump(qt_app)
        assert box.text().split() == ["سلام", "چطوری"], f"در کادر: {box.text()!r}"

    def test_nothing_converts_until_the_word_is_finished(self, qt_app, box):
        # No candidate box was the explicit request, so the only signal that a
        # word ended is the space. Converting early would rewrite letters while
        # they are still being typed.
        type_keys(qt_app, "salam")
        pump(qt_app)
        assert box.text() == "salam", f"زودتر از موعد عوض شد: {box.text()!r}"


class TestAndThenItLandsInTheOtherWindow:
    def test_ctrl_enter_writes_the_persian_into_the_target(self, qt_app, target, box):
        # `target` before `box` on purpose: fixtures build in argument order, and
        # the destination window grabs the foreground as it opens. Built last,
        # the box keeps the keyboard.
        written: list[str] = []
        box.insertRequested.connect(written.append)
        focus_box(qt_app, box)
        type_keys(qt_app, "salam ")
        pump(qt_app)
        assert box.text().strip() == "سلام", f"کلیدها به کادر نرسیدند: {box.text()!r}"

        send_input(
            [
                key_input(vk=VK_CONTROL),
                key_input(vk=VK_RETURN),
                key_input(vk=VK_RETURN, flags=KEYEVENTF_KEYUP),
                key_input(vk=VK_CONTROL, flags=KEYEVENTF_KEYUP),
            ]
        )
        pump(qt_app, 0.6)
        assert written, "Ctrl+Enter هیچ متنی نفرستاد"

        # The app's own step: take what the box settled on to the window the
        # user was in before. Driven here rather than mocked, because the focus
        # hand-off is the part that has never been exercised.
        inject.insert(target.hwnd, written[-1].strip())
        assert target.wait_for("سلام"), f"در پنجره‌ی مقصد: {target.text()!r}"
