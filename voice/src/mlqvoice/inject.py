"""Putting the finished text back where the user was typing.

The hard part is not the typing, it is the focus.  By the time the user presses
"بنویس", the foreground window is *our* overlay — so the target window has to be
remembered at the moment the hotkey fired, and handed the focus back before a
single key is sent.  Windows deliberately makes ``SetForegroundWindow`` fail for
a process that is not the foreground one, and the documented way around it is to
attach to the target's input queue first.
"""

from __future__ import annotations

import contextlib
import ctypes
import time
from ctypes import wintypes

from .win32 import (
    CF_UNICODETEXT,
    GMEM_MOVEABLE,
    INPUT,
    KEYEVENTF_KEYUP,
    SW_RESTORE,
    VK_CONTROL,
    VK_RETURN,
    SendFailed,
    kernel32,
    key_input,
    send_input,
    unicode_inputs,
    user32,
)


class InjectError(RuntimeError):
    """Something in the focus/clipboard/typing chain refused to co-operate."""


def window_pid(hwnd: int) -> int:
    """Which process owns *hwnd*, or 0 if it cannot be told."""
    if not hwnd:
        return 0
    pid = wintypes.DWORD(0)
    user32().GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def capture_target(reject_pids: set[int] | None = None) -> int:
    """The window the user was in — call this *before* showing the overlay.

    *reject_pids* is how our own recogniser browser is kept out. It steals the
    foreground for a moment while Chrome cold-starts, and a hotkey press in that
    window captured **it** as the destination: the box then offered to type the
    user's sentence into an off-screen window they could not even see. Refusing
    those windows returns 0, which the insert path already reports as "no
    destination" rather than typing somewhere random.
    """
    hwnd = int(user32().GetForegroundWindow())
    if reject_pids and window_pid(hwnd) in reject_pids:
        return 0
    return hwnd


def window_title(hwnd: int) -> str:
    """Best-effort title, used only to tell the user where the text will land."""
    if not hwnd:
        return ""
    u = user32()
    length = int(u.GetWindowTextLengthW(wintypes.HWND(hwnd)))
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    u.GetWindowTextW(wintypes.HWND(hwnd), buf, length + 1)
    return buf.value


def _send(inputs: list[INPUT]) -> None:
    """``send_input``, but failing as an :class:`InjectError` like its neighbours.

    Callers here catch ``InjectError`` and show it to the user; a bare
    ``SendFailed`` escaping this module would reach them as a traceback instead.
    """
    try:
        send_input(inputs)
    except SendFailed as exc:
        raise InjectError(str(exc)) from exc


def focus_window(hwnd: int, *, timeout: float = 1.0) -> bool:
    """Bring *hwnd* to the foreground, returning whether it actually got there.

    The return value matters: if focus never moved, typing would spray the text
    into whatever *is* focused, which at best is the overlay and at worst is a
    terminal about to run it.  Callers must not type on ``False``.
    """
    if not hwnd:
        return False
    u, k = user32(), kernel32()
    hwnd_t = wintypes.HWND(hwnd)

    if u.IsIconic(hwnd_t):
        u.ShowWindow(hwnd_t, SW_RESTORE)

    ours = k.GetCurrentThreadId()
    theirs = u.GetWindowThreadProcessId(hwnd_t, None)

    attached = bool(u.AttachThreadInput(ours, theirs, True)) if ours != theirs else False
    try:
        u.SetForegroundWindow(hwnd_t)
        u.SetActiveWindow(hwnd_t)
    finally:
        if attached:
            u.AttachThreadInput(ours, theirs, False)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if int(u.GetForegroundWindow()) == hwnd:
            return True
        time.sleep(0.02)
    return int(u.GetForegroundWindow()) == hwnd


# -- clipboard -----------------------------------------------------------


def _open_clipboard(retries: int = 10) -> None:
    """Another process can hold the clipboard; a few retries beats failing."""
    u = user32()
    for _ in range(retries):
        if u.OpenClipboard(None):
            return
        time.sleep(0.03)
    raise InjectError("کلیپ‌بورد در اختیارِ برنامه‌ی دیگری است")


def get_clipboard_text() -> str | None:
    """Current clipboard text, or ``None`` when it holds something else."""
    u, k = user32(), kernel32()
    _open_clipboard()
    try:
        if not u.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = u.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        k.GlobalLock.restype = ctypes.c_void_p
        ptr = k.GlobalLock(ctypes.c_void_p(handle))
        if not ptr:
            return None
        try:
            return ctypes.c_wchar_p(ptr).value
        finally:
            k.GlobalLock.restype = ctypes.c_int
            k.GlobalUnlock(ctypes.c_void_p(handle))
    finally:
        u.CloseClipboard()


def set_clipboard_text(text: str) -> None:
    u, k = user32(), kernel32()
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)

    k.GlobalAlloc.restype = ctypes.c_void_p
    handle = k.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        raise InjectError("حافظه برای کلیپ‌بورد گرفته نشد")

    k.GlobalLock.restype = ctypes.c_void_p
    ptr = k.GlobalLock(ctypes.c_void_p(handle))
    if not ptr:
        raise InjectError("قفلِ حافظه‌ی کلیپ‌بورد نشد")
    ctypes.memmove(ptr, data, size)
    k.GlobalUnlock(ctypes.c_void_p(handle))

    _open_clipboard()
    try:
        u.EmptyClipboard()
        # Ownership of the handle passes to the clipboard on success only.
        if not u.SetClipboardData(CF_UNICODETEXT, ctypes.c_void_p(handle)):
            raise InjectError("نوشتن در کلیپ‌بورد رد شد")
    finally:
        u.CloseClipboard()


# -- typing --------------------------------------------------------------


def press_ctrl_v() -> None:
    _send(
        [
            key_input(vk=VK_CONTROL),
            key_input(vk=ord("V")),
            key_input(vk=ord("V"), flags=KEYEVENTF_KEYUP),
            key_input(vk=VK_CONTROL, flags=KEYEVENTF_KEYUP),
        ]
    )


def type_text(text: str, *, chunk: int = 40, pause: float = 0.004) -> None:
    """Type *text* one character at a time.

    Slower than pasting and it loses to applications that swallow fast input, but
    it is the only option where paste is blocked or rebound.  Newline is sent as
    a real Return key: a Unicode ``\\n`` is ignored by most edit controls.
    """
    batch: list[INPUT] = []
    for ch in text:
        if ch == "\n":
            batch += [key_input(vk=VK_RETURN), key_input(vk=VK_RETURN, flags=KEYEVENTF_KEYUP)]
        elif ch == "\r":
            continue
        else:
            batch += unicode_inputs(ch)
        if len(batch) >= chunk:
            _send(batch)
            batch = []
            time.sleep(pause)
    _send(batch)


def insert(
    hwnd: int,
    text: str,
    *,
    mode: str = "paste",
    restore_clipboard: bool = True,
    settle: float = 0.06,
) -> None:
    """Focus *hwnd* and put *text* into it.

    Raises rather than failing quietly: a button that appears to do nothing is
    the single worst outcome here, because the user has already spoken the text
    and has no idea whether it was lost.
    """
    if not text:
        return
    if not focus_window(hwnd):
        raise InjectError("پنجره‌ی مقصد فوکوس نگرفت — متن جایی نوشته نشد")

    # Give the target a moment to finish activating before keys arrive.
    time.sleep(settle)

    if mode == "type":
        type_text(text)
        return
    if mode != "paste":
        raise InjectError(f"حالتِ نوشتنِ ناشناخته: {mode!r}")

    saved = get_clipboard_text() if restore_clipboard else None
    set_clipboard_text(text)
    try:
        press_ctrl_v()
        # Let the target read the clipboard before we take it back.
        time.sleep(0.12)
    finally:
        if restore_clipboard and saved is not None:
            # The text already landed; a stale clipboard is not worth an error.
            with contextlib.suppress(InjectError):
                set_clipboard_text(saved)
