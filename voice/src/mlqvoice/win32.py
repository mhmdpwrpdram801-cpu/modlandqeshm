"""The Win32 surface the app needs, in one place.

Structures are defined unconditionally so their layout can be tested anywhere;
only the calls into ``user32``/``kernel32`` require actually running on Windows.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

# -- constants -----------------------------------------------------------

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_MENU = 0x12
VK_SHIFT = 0x10
VK_LWIN = 0x5B

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

SW_RESTORE = 9


class NotWindows(RuntimeError):
    """Raised when a Windows-only call is attempted elsewhere."""


class SendFailed(RuntimeError):
    """``SendInput`` accepted fewer events than it was given."""


# -- structures ----------------------------------------------------------
#
# Fixed-width types, not ``wintypes``.  ``wintypes.DWORD`` is ``c_ulong``, which
# is 4 bytes on Windows but 8 on 64-bit Linux — so the struct layout would depend
# on where the module happened to be imported, and ``SendInput`` rejects the whole
# batch when ``cbSize`` disagrees with what it expects.  Windows' WORD/DWORD/LONG
# are 16/32/32 bits everywhere, so spelling them out makes the layout constant
# and lets the sizes be asserted off Windows.

WORD = ctypes.c_uint16
DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", WORD),
        ("wScan", WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", LONG),
        ("dy", LONG),
        ("mouseData", DWORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", DWORD),
        ("wParamL", WORD),
        ("wParamH", WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]  # noqa: RUF012


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", DWORD), ("u", _INPUTUNION)]


def key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    """One keyboard event, ready to hand to ``SendInput``."""
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags))


def unicode_inputs(char: str) -> list[INPUT]:
    """Key-down/key-up pair that types *char* regardless of keyboard layout.

    ``KEYEVENTF_UNICODE`` is what makes Persian typable without the user having a
    Persian layout selected: the character travels as a UTF-16 code unit rather
    than as a key position.  Characters outside the BMP arrive as two units and
    must be sent as a surrogate pair, unsplit.
    """
    raw = char.encode("utf-16-le", "surrogatepass")
    out: list[INPUT] = []
    for i in range(0, len(raw), 2):
        unit = int.from_bytes(raw[i : i + 2], "little")
        out.append(key_input(scan=unit, flags=KEYEVENTF_UNICODE))
        out.append(key_input(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    return out


def send_input(inputs: list[INPUT]) -> None:
    """Hand a batch of events to ``SendInput``.

    Sent as one array rather than one call per event: Windows delivers a batch
    atomically, so nothing the user physically types can land in the middle of a
    modifier combination and turn ``Ctrl+V`` into a bare ``V``.

    A short count is an error, not a warning.  ``SendInput`` drops the *rest* of
    the batch when it refuses one event — usually because a more privileged
    window has the foreground — and half a key combination is worse than none.
    """
    if not inputs:
        return
    array = (INPUT * len(inputs))(*inputs)
    sent = user32().SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise SendFailed(f"SendInput فقط {sent} از {len(inputs)} رویداد را فرستاد")


# -- libraries -----------------------------------------------------------
#
# Every function below that hands back a **pointer** needs its restype declared.
# ctypes defaults to ``c_int`` — 32 bits — so on 64-bit Windows the top half of
# a returned pointer is thrown away and what is left is sign-extended back into
# something that looks like an address but is not one.
#
# This is not theoretical. ``GetClipboardData`` returns an ``HGLOBAL``, which is
# a real pointer; the truncated value went into ``GlobalLock``, and reading the
# string it pointed at crashed the process with an access violation on Windows
# CI. It had never been caught because nothing had ever read the clipboard on a
# 64-bit machine before, and because the failure depends on where Windows
# happened to put the block — the same code is perfectly fine whenever the top
# 32 bits are zero, which is most of the time.
#
# Window handles are the exception and are safe to truncate: Microsoft
# guarantees USER handles fit in 32 bits so 32-bit processes can be given them.
# Declaring them anyway costs nothing and means nobody has to remember which
# rule applies to which handle.

_PROTOTYPES_DONE = False


def _declare(u, k) -> None:
    """Pin down argument and return types once, for the whole process."""
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.GetClipboardData.restype = ctypes.c_void_p
    u.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    u.SetClipboardData.restype = ctypes.c_void_p
    u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    u.IsClipboardFormatAvailable.restype = wintypes.BOOL
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.OpenClipboard.restype = wintypes.BOOL
    u.CloseClipboard.argtypes = []
    u.CloseClipboard.restype = wintypes.BOOL
    u.EmptyClipboard.argtypes = []
    u.EmptyClipboard.restype = wintypes.BOOL

    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wintypes.HWND
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.SetForegroundWindow.restype = wintypes.BOOL
    u.SetActiveWindow.argtypes = [wintypes.HWND]
    u.SetActiveWindow.restype = wintypes.HWND
    u.IsIconic.argtypes = [wintypes.HWND]
    u.IsIconic.restype = wintypes.BOOL
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsWindowVisible.restype = wintypes.BOOL
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow.restype = wintypes.BOOL
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.restype = ctypes.c_int
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowTextW.restype = ctypes.c_int
    u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    u.AttachThreadInput.restype = wintypes.BOOL
    # GetWindowThreadProcessId keeps its argtypes free on purpose — callers pass
    # either a byref(DWORD) or None for the second argument, and a fixed list
    # would reject one of them. The **restype** has no such excuse: it hands
    # back a DWORD thread id, and ctypes' default c_int makes anything above
    # 2^31 come back negative. Same family as the truncated HGLOBAL that
    # crashed CI, just quieter.
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
    u.SendInput.restype = wintypes.UINT

    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.restype = wintypes.BOOL
    k.GlobalFree.argtypes = [ctypes.c_void_p]
    k.GlobalFree.restype = ctypes.c_void_p
    k.GetCurrentThreadId.argtypes = []
    k.GetCurrentThreadId.restype = wintypes.DWORD


_LIBS: tuple | None = None


def _libs():
    """The two libraries, loaded once, with the error code actually kept.

    ``ctypes.windll.user32`` — the obvious spelling, and the one this used —
    does **not** save the Win32 last-error. ``ctypes.get_last_error()`` reads a
    private copy that is only filled in for libraries loaded with
    ``use_last_error=True``, so without the flag it answers ``0`` forever.

    That was not academic: :mod:`mlqvoice.hotkey` prints that number when
    registering the hotkey fails, and the one clue that would say *why* —
    ``1409``, somebody else already owns this combination — was being reported
    as zero every single time.

    Loading them ourselves means caching them ourselves, because ``WinDLL``
    builds a fresh object per call and the declarations below would be lost.
    """
    global _LIBS
    if not IS_WINDOWS:
        raise NotWindows("این بخش فقط روی ویندوز کار می‌کند")
    if _LIBS is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        _declare(u, k)
        _LIBS = (u, k)
    return _LIBS


def user32():
    return _libs()[0]


def kernel32():
    return _libs()[1]
