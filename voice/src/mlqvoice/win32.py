"""The Win32 surface the app needs, in one place.

Structures are defined unconditionally so their layout can be tested anywhere;
only the calls into ``user32``/``kernel32`` require actually running on Windows.
"""

from __future__ import annotations

import ctypes
import sys

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


def user32():
    if not IS_WINDOWS:
        raise NotWindows("این بخش فقط روی ویندوز کار می‌کند")
    return ctypes.windll.user32


def kernel32():
    if not IS_WINDOWS:
        raise NotWindows("این بخش فقط روی ویندوز کار می‌کند")
    return ctypes.windll.kernel32
