"""Run the packaged exe in a real console and read the screen back.

Every other check of the exe captures its output with a redirect, and that
quietly answers a different question. A redirected handle is a real handle, and
the console's code page never enters into it — so the one path that always
works was the only path ever measured.

What the owner actually does is type ``mlqvoice check`` at a prompt. A
``--windowed`` build owns no console, so ``launcher.py`` borrows the shell's —
and a borrowed console keeps whatever code page Windows gave it. Nothing had
ever looked at what actually lands on the screen, so whether the Persian
arrives readable was simply unknown. This is how it gets known.

So this allocates a genuine console, starts the exe as a child of it with no
redirection whatsoever, waits, and then reads the characters off the screen
buffer. That is the only way to observe what the owner would see.

    python console_probe.py <exe> <transcript.txt> [args...]

Exit codes: 0 the exe ran and the screen was captured · 1 the exe failed · 2 the
probe itself could not work, which is a different thing entirely and must never
be reported as "the app printed nothing" (CORE-05).
"""

from __future__ import annotations

import ctypes
import pathlib
import subprocess
import sys
from ctypes import wintypes

SELFTEST_MARKER = "MLQPROBE-SELFTEST-OK"

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value

STD_INPUT_HANDLE = 0xFFFFFFF6  # (DWORD)-10
STD_OUTPUT_HANDLE = 0xFFFFFFF5  # (DWORD)-11
STD_ERROR_HANDLE = 0xFFFFFFF4  # (DWORD)-12
HANDLE_FLAG_INHERIT = 0x00000001


class ProbeBroken(RuntimeError):
    """The measurement could not be taken — never the same thing as a bad result."""


class COORD(ctypes.Structure):
    _fields_ = (("X", ctypes.c_short), ("Y", ctypes.c_short))


class SMALL_RECT(ctypes.Structure):
    _fields_ = (
        ("Left", ctypes.c_short),
        ("Top", ctypes.c_short),
        ("Right", ctypes.c_short),
        ("Bottom", ctypes.c_short),
    )


class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = (
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", ctypes.c_ushort),
        ("srWindow", SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    )


def k32():
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    lib.CreateFileW.restype = ctypes.c_void_p
    lib.GetConsoleScreenBufferInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
    lib.ReadConsoleOutputCharacterW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPWSTR,
        wintypes.DWORD,
        COORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    lib.ReadConsoleOutputCharacterW.restype = wintypes.BOOL
    lib.CloseHandle.argtypes = [ctypes.c_void_p]
    lib.CloseHandle.restype = wintypes.BOOL
    lib.SetStdHandle.argtypes = [wintypes.DWORD, ctypes.c_void_p]
    lib.SetStdHandle.restype = wintypes.BOOL
    lib.GetConsoleOutputCP.argtypes = []
    lib.GetConsoleOutputCP.restype = wintypes.UINT
    lib.SetHandleInformation.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    lib.SetHandleInformation.restype = wintypes.BOOL
    return lib


def open_console(lib, name: str, access: int):
    """A handle on the console — and one a child process can actually use.

    ``CreateFileW`` hands back a **non-inheritable** handle unless told
    otherwise, and that detail decides whether any of this works. A child
    started without ``STARTF_USESTDHANDLES`` inherits the parent's standard
    handle *values*; if those values are not inheritable the child receives
    numbers that mean nothing in its own process, its writes fail, and the
    output goes nowhere at all — not to the screen, not to the log.

    That is precisely what the second run showed: the marker vanished from
    both. Marking the handle inheritable is the whole fix.
    """
    handle = lib.CreateFileW(
        name,
        access,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle in (0, INVALID_HANDLE, None):
        raise ProbeBroken(f"{name} باز نشد (خطای {ctypes.get_last_error()})")
    if not lib.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT):
        raise ProbeBroken(f"{name} ارث‌بردنی نشد (خطای {ctypes.get_last_error()})")
    return handle


def take_over_std_handles(lib) -> None:
    """Point the process's standard handles at the console we just made.

    ``AllocConsole`` only fills in standard handles that were *unset*. Under a
    CI runner they are already set — to the pipe the log is read from — so the
    new console gets ignored and every child keeps writing into that pipe.

    That is exactly what happened on the first run: the marker turned up in the
    Actions log while the console screen stayed empty. The self-test caught it
    and said "the tool is broken", which is the whole reason it exists; without
    it the report would have read "the app printed nothing".

    Note this does not disturb the probe's own ``print``: Python writes to file
    descriptor 1, which ``SetStdHandle`` leaves alone. So the probe still talks
    to the log while its children talk to the console.
    """
    for which, name, access in (
        (STD_OUTPUT_HANDLE, "CONOUT$", GENERIC_READ | GENERIC_WRITE),
        (STD_ERROR_HANDLE, "CONOUT$", GENERIC_READ | GENERIC_WRITE),
        (STD_INPUT_HANDLE, "CONIN$", GENERIC_READ | GENERIC_WRITE),
    ):
        if not lib.SetStdHandle(which, open_console(lib, name, access)):
            raise ProbeBroken(f"SetStdHandle برای {name} شکست خورد")


def read_screen() -> str:
    """Everything written to the console so far, as text."""
    lib = k32()
    handle = open_console(lib, "CONOUT$", GENERIC_READ | GENERIC_WRITE)
    try:
        info = CONSOLE_SCREEN_BUFFER_INFO()
        if not lib.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
            raise ProbeBroken(f"اندازه‌ی صفحه‌ی کنسول خوانده نشد ({ctypes.get_last_error()})")
        width = info.dwSize.X
        # Only down to the cursor: the rest of the buffer is blank padding and
        # would bury the few lines that matter under thousands of spaces.
        rows = info.dwCursorPosition.Y + 1
        total = width * rows
        buf = ctypes.create_unicode_buffer(total + 1)
        got = wintypes.DWORD(0)
        if not lib.ReadConsoleOutputCharacterW(handle, buf, total, COORD(0, 0), ctypes.byref(got)):
            raise ProbeBroken(f"محتوای صفحه‌ی کنسول خوانده نشد ({ctypes.get_last_error()})")
        raw = buf[: got.value]
    finally:
        lib.CloseHandle(handle)
    lines = [raw[i : i + width].rstrip() for i in range(0, len(raw), width)]
    return "\n".join(lines).strip()


def run_in_console(command: list[str], timeout: int) -> int:
    """Start *command* attached to our console, with nothing redirected."""
    proc = subprocess.Popen(command, close_fds=False)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise


def main(argv: list[str]) -> int:
    if sys.platform != "win32":
        print("این ابزار فقط روی ویندوز معنی دارد.", file=sys.stderr)
        return 2
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    exe, transcript, args = argv[0], pathlib.Path(argv[1]), argv[2:]
    lib = k32()
    try:
        lib.FreeConsole()  # a runner step has none, but be explicit rather than lucky
        if not lib.AllocConsole():
            raise ProbeBroken(f"کنسول ساخته نشد (خطای {ctypes.get_last_error()})")
        take_over_std_handles(lib)

        # Before trusting a blank screen: prove the screen can be read at all.
        # A probe that silently reads nothing would report every build as
        # broken, and that report is indistinguishable from the real bug.
        echoed = run_in_console(["cmd", "/c", f"echo {SELFTEST_MARKER}"], timeout=30)
        proof = read_screen()
        if SELFTEST_MARKER not in proof:
            # The echo's own exit code is in the message on purpose: a failure
            # to write shows up there, and without it the next round is another
            # blind guess at why the screen was empty.
            raise ProbeBroken(
                f"نشانه‌ی محکِ خودِ آزمایش روی صفحه نیامد "
                f"(کدِ خروجیِ echo: {echoed}). خوانده شد: {proof!r}"
            )
    except ProbeBroken as exc:
        print(f"::error::{exc} — این ایرادِ خودِ آزمایش است، نه برنامه", file=sys.stderr)
        return 2

    # Printed rather than asserted: the point is to see what a plain console
    # hands the exe, not to pin the runner's locale down.
    print(f"کدپیجِ کنسولِ تازه پیش از اجرا: {lib.GetConsoleOutputCP()}")

    try:
        code = run_in_console([exe, *args], timeout=120)
    except subprocess.TimeoutExpired:
        print("::error::exe در کنسول برنگشت — گیر کرده", file=sys.stderr)
        return 1

    try:
        screen = read_screen()
    except ProbeBroken as exc:
        print(f"::error::{exc} — این ایرادِ خودِ آزمایش است، نه برنامه", file=sys.stderr)
        return 2

    # Drop everything up to and including the self-test marker, so the caller
    # sees only what the exe itself put on the screen.
    _, _, after = screen.partition(SELFTEST_MARKER)
    transcript.write_text(after.strip(), encoding="utf-8")
    print(f"کدپیجِ کنسول پس از اجرا: {lib.GetConsoleOutputCP()}")
    print(f"exe با کدِ {code} برگشت، {len(after.strip())} نویسه روی کنسول نوشت.")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
