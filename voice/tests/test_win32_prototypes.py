"""Pointer-returning Win32 calls must say they return pointers.

The bug this exists to stop, found by ``test_inject_windows.py`` on its very
first run: ``GetClipboardData`` returns an ``HGLOBAL``, ctypes assumed the
default ``c_int``, and on 64-bit Windows the top half of the address was thrown
away. ``GlobalLock`` was then handed a plausible-looking non-address, and
reading the string it pointed at killed the process with an access violation.

Two things make this class of bug worth a test of its own rather than a fix and
a shrug:

* **It hides.** The truncated value is only wrong when the top 32 bits are
  non-zero, so the same code works nearly every time and fails on a machine
  that happens to place the block higher — the owner's, eventually.
* **It is decidable off Windows.** Whether a declaration is right is a property
  of the declaration, not of the run, so this file gates the fix on Linux too —
  which matters, because everything that could *execute* it is Windows-only and
  would sit unrun on every ordinary gate.
"""

from __future__ import annotations

import ctypes
from unittest import mock

from mlqvoice import win32


class Recorder:
    """Stands in for a ctypes function, remembering what was declared on it."""

    def __init__(self):
        self.argtypes = None
        self.restype = None


class FakeLib:
    def __init__(self):
        self._fns: dict[str, Recorder] = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._fns.setdefault(name, Recorder())


def declared() -> tuple[FakeLib, FakeLib]:
    u, k = FakeLib(), FakeLib()
    win32._declare(u, k)
    return u, k


#: Every call whose return value is dereferenced or handed back to Windows as a
#: handle. ``c_int`` on any of these is the crash described above.
POINTER_RETURNS = [
    ("user32", "GetClipboardData"),
    ("user32", "SetClipboardData"),
    ("user32", "GetForegroundWindow"),
    ("user32", "SetActiveWindow"),
    ("kernel32", "GlobalAlloc"),
    ("kernel32", "GlobalLock"),
    ("kernel32", "GlobalFree"),
]

POINTER_SIZED = {ctypes.c_void_p, ctypes.wintypes.HWND, ctypes.wintypes.HANDLE}


class TestNothingReturningAPointerIsTruncated:
    def test_every_pointer_returning_call_is_declared(self):
        u, k = declared()
        libs = {"user32": u, "kernel32": k}
        wrong = [
            f"{lib}.{fn}"
            for lib, fn in POINTER_RETURNS
            if getattr(libs[lib], fn).restype not in POINTER_SIZED
        ]
        assert not wrong, f"این‌ها هنوز مقدارِ برگشتیِ ۳۲بیتی دارند: {wrong}"

    def test_the_sizes_really_are_the_machine_word(self):
        # Guards the guard: if wintypes.HWND were ever an int alias, the test
        # above would pass while declaring nothing useful.
        for tp in POINTER_SIZED:
            assert ctypes.sizeof(tp) == ctypes.sizeof(ctypes.c_void_p)

    def test_the_memory_handle_is_passed_back_as_a_pointer_too(self):
        # Declaring only the return type would still truncate on the way *in*.
        _, k = declared()
        assert k.GlobalLock.argtypes == [ctypes.c_void_p]
        assert k.GlobalUnlock.argtypes == [ctypes.c_void_p]
        assert k.GlobalFree.argtypes == [ctypes.c_void_p]

    def test_setclipboarddata_takes_the_handle_as_a_pointer(self):
        u, _ = declared()
        assert u.SetClipboardData.argtypes[1] is ctypes.c_void_p


class TestTheyAreDeclaredExactlyOnce:
    def test_the_second_call_does_not_redeclare(self, monkeypatch):
        # ctypes hands back the same library object every time, so re-declaring
        # is merely wasteful — but the flag is also what makes it safe to call
        # user32() on a hot path, so it is worth knowing it works.
        monkeypatch.setattr(win32, "IS_WINDOWS", True)
        monkeypatch.setattr(win32, "_PROTOTYPES_DONE", False)
        calls = []
        fake = FakeLib()

        class Windll:
            user32 = fake
            kernel32 = FakeLib()

        # raising=False because ctypes has no `windll` at all off Windows —
        # which is the whole reason this test can run on the Linux gate.
        monkeypatch.setattr(ctypes, "windll", Windll, raising=False)
        with mock.patch.object(win32, "_declare", lambda u, k: calls.append(1)):
            win32.user32()
            win32.user32()
            win32.kernel32()
        assert calls == [1]

    def test_off_windows_it_refuses_rather_than_declaring(self, monkeypatch):
        import pytest

        monkeypatch.setattr(win32, "IS_WINDOWS", False)
        with pytest.raises(win32.NotWindows):
            win32.user32()
