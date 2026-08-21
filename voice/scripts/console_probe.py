"""Run the packaged exe in a real console and read the screen back.

Every other check of the exe captures its output with a redirect, and that
quietly answers a different question. A redirected handle is a real handle, and
the console's code page never enters into it — so the one path that always
works was the only path ever measured.

What the owner actually does is type ``mlqvoice check`` at a prompt. A
``--windowed`` build owns no console, so ``launcher.py`` borrows the shell's;
that borrowed console keeps whatever code page Windows gave it, and until this
probe existed nothing had ever looked at what landed on the screen. Persian
came out as ``Ø§Ø¬…`` — output that exists and is useless.

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
    return lib


def read_screen() -> str:
    """Everything written to the console so far, as text."""
    lib = k32()
    handle = lib.CreateFileW(
        "CONOUT$",
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle in (0, INVALID_HANDLE, None):
        raise OSError(ctypes.get_last_error(), "CONOUT$ باز نشد")
    try:
        info = CONSOLE_SCREEN_BUFFER_INFO()
        if not lib.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
            raise OSError(ctypes.get_last_error(), "اندازه‌ی صفحه‌ی کنسول خوانده نشد")
        width = info.dwSize.X
        # Only down to the cursor: the rest of the buffer is blank padding and
        # would bury the few lines that matter under thousands of spaces.
        rows = info.dwCursorPosition.Y + 1
        total = width * rows
        buf = ctypes.create_unicode_buffer(total + 1)
        got = wintypes.DWORD(0)
        if not lib.ReadConsoleOutputCharacterW(handle, buf, total, COORD(0, 0), ctypes.byref(got)):
            raise OSError(ctypes.get_last_error(), "محتوای صفحه‌ی کنسول خوانده نشد")
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
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.FreeConsole()  # a runner step has none, but be explicit rather than lucky
    if not lib.AllocConsole():
        print(
            f"::error::کنسول ساخته نشد (خطای {ctypes.get_last_error()}) — "
            "این ایرادِ خودِ آزمایش است، نه برنامه",
            file=sys.stderr,
        )
        return 2

    # Before trusting a blank screen: prove the screen can be read at all. A
    # probe that silently reads nothing would report every build as broken, and
    # the report would be indistinguishable from the real bug.
    try:
        run_in_console(["cmd", "/c", f"echo {SELFTEST_MARKER}"], timeout=30)
        proof = read_screen()
    except OSError as exc:
        print(f"::error::صفحه‌ی کنسول خوانده نشد: {exc} — ایرادِ آزمایش است", file=sys.stderr)
        return 2
    if SELFTEST_MARKER not in proof:
        print(
            "::error::خودِ آزمایش کار نمی‌کند: نشانه‌ی محکِ خودش هم روی صفحه نیامد. "
            f"چیزی که خوانده شد: {proof!r}",
            file=sys.stderr,
        )
        return 2

    try:
        code = run_in_console([exe, *args], timeout=120)
    except subprocess.TimeoutExpired:
        print("::error::exe در کنسول برنگشت — گیر کرده", file=sys.stderr)
        return 1

    screen = read_screen()
    # Drop everything up to and including the self-test marker, so the caller
    # sees only what the exe itself put on the screen.
    _, _, after = screen.partition(SELFTEST_MARKER)
    transcript.write_text(after.strip(), encoding="utf-8")
    print(f"exe با کدِ {code} برگشت، {len(after.strip())} نویسه روی کنسول نوشت.")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
