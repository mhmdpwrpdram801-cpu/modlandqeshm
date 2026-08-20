"""Text actually arriving in another program's window.

This closes the biggest hole in the honest list in the README: every part of
``inject`` was reasoned about and its structures checked, but no character had
ever been typed into a real window by this code. ``sizeof(INPUT) == 40`` says
the struct is shaped right; it says nothing about whether the focus dance works
or whether the paste lands.

What each of these actually exercises, end to end and across a process
boundary: ``AttachThreadInput`` + ``SetForegroundWindow`` to steal focus back,
``SendInput`` for real keystrokes, and the clipboard save/restore around the
paste. If any of it is wrong the user presses "تمام شد" and their sentence goes
nowhere — the single worst outcome this program has, because by then they have
already said it.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="مسیرِ Win32 فقط روی ویندوز اجرا می‌شود")

if os.name == "nt":  # importing these off Windows raises, and would kill collection
    from mlqvoice import inject
    from mlqvoice.win32 import user32

TARGET = Path(__file__).parent / "target_window.py"


def _windows_of(pid: int) -> list[int]:
    """Every visible top-level window belonging to *pid*."""
    found: list[int] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        owner = wintypes.DWORD(0)
        user32().GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32().IsWindowVisible(hwnd):
            found.append(int(hwnd))
        return True

    user32().EnumWindows(proc(visit), 0)
    return found


class Target:
    """A live window in another process, plus a way to read what it holds."""

    def __init__(self, proc: subprocess.Popen, path: Path, hwnd: int):
        self.proc, self.path, self.hwnd = proc, path, hwnd

    def text(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def wait_for(self, expected: str, timeout: float = 15.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.text() == expected:
                return True
            time.sleep(0.05)
        return False


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "typed.txt"
    # The rest of the suite runs offscreen, and inheriting that here would give
    # us a window the compositor knows nothing about: EnumWindows finds no
    # handle, SendInput has nowhere to land, and the failure looks like a Win32
    # bug instead of a test that never had a window in the first place.
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    proc = subprocess.Popen([sys.executable, str(TARGET), str(path)], env=env)
    try:
        deadline = time.monotonic() + 30
        hwnds: list[int] = []
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"پنجره‌ی هدف بالا نیامد — کدِ خروجی {proc.returncode}")
            # Both conditions matter: the file says Qt got as far as showing the
            # box, the window handle says the OS agrees there is something to
            # aim at. Waiting on only one of them raced on a slow runner.
            if path.exists() and (hwnds := _windows_of(proc.pid)):
                break
            time.sleep(0.1)
        else:
            pytest.fail("پنجره‌ی هدف تا ۳۰ ثانیه ظاهر نشد")
        time.sleep(0.4)  # let it finish activating before anyone steals focus
        yield Target(proc, path, hwnds[0])
    finally:
        proc.terminate()
        proc.wait(timeout=10)


class TestTheTextArrives:
    def test_pasting_persian_into_another_window(self, target):
        inject.insert(target.hwnd, "سلام دنیا")
        assert target.wait_for("سلام دنیا"), f"چیزی که رسید: {target.text()!r}"

    def test_typing_it_key_by_key_works_too(self, target):
        # The fallback for applications that swallow Ctrl+V. Slower, and it goes
        # through unicode_inputs rather than the clipboard, so it is a genuinely
        # different path — worth its own run.
        inject.insert(target.hwnd, "خوبی", mode="type")
        assert target.wait_for("خوبی"), f"چیزی که رسید: {target.text()!r}"

    def test_a_long_sentence_is_not_truncated(self, target):
        # type_text batches in chunks of 40 inputs; a sentence long enough to
        # span several batches is the only way to find out whether the seams
        # hold. Persian doubles the input count, since each character needs a
        # down and an up event.
        sentence = "این یک جمله‌ی بلند است که باید کامل و بدونِ افتادگی برسد"
        inject.insert(target.hwnd, sentence, mode="type")
        assert target.wait_for(sentence), f"چیزی که رسید: {target.text()!r}"

    def test_newlines_arrive_as_real_line_breaks(self, target):
        # A Unicode "\n" sent as a character is ignored by most edit controls,
        # which is why type_text sends VK_RETURN instead. If that regressed the
        # text would arrive as one run-on line and nobody would notice.
        inject.insert(target.hwnd, "خطِ اول\nخطِ دوم", mode="type")
        assert target.wait_for("خطِ اول\nخطِ دوم"), f"چیزی که رسید: {target.text()!r}"


class TestTheClipboardIsGivenBack:
    def test_what_was_there_before_is_restored(self, target):
        # The user was probably in the middle of copying something. Eating their
        # clipboard to paste ours would be a small theft they discover later.
        inject.set_clipboard_text("چیزی که کاربر کپی کرده بود")
        inject.insert(target.hwnd, "متنِ ما")
        assert target.wait_for("متنِ ما")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if inject.get_clipboard_text() == "چیزی که کاربر کپی کرده بود":
                return
            time.sleep(0.05)
        pytest.fail(f"کلیپ‌بورد برنگشت: {inject.get_clipboard_text()!r}")

    def test_it_can_be_told_not_to_bother(self, target):
        inject.set_clipboard_text("قدیمی")
        inject.insert(target.hwnd, "تازه", restore_clipboard=False)
        assert target.wait_for("تازه")
        assert inject.get_clipboard_text() == "تازه"


class TestFocus:
    def test_the_target_really_comes_forward(self, target):
        assert inject.focus_window(target.hwnd)
        assert int(user32().GetForegroundWindow()) == target.hwnd

    def test_a_dead_window_is_refused_rather_than_typed_into(self, target):
        # The important half: focus_window returning False is what stops insert
        # from spraying the sentence into whatever *is* focused.
        target.proc.terminate()
        target.proc.wait(timeout=10)
        assert not inject.focus_window(target.hwnd, timeout=0.3)
        with pytest.raises(inject.InjectError):
            inject.insert(target.hwnd, "نباید جایی برود")

    def test_no_window_at_all_is_refused(self):
        assert not inject.focus_window(0)
        with pytest.raises(inject.InjectError):
            inject.insert(0, "هیچ‌جا")


class TestTheTitleWeShowTheUser:
    def test_the_target_window_is_named(self, target):
        assert inject.window_title(target.hwnd) == "mlqvoice-target"

    def test_and_it_is_owned_by_the_process_we_started(self, target):
        assert inject.window_pid(target.hwnd) == target.proc.pid

    def test_our_own_window_would_be_refused_as_a_destination(self, target):
        # capture_target's reject list, against a real window this time.
        assert inject.capture_target({target.proc.pid}) != target.hwnd
