"""The global hotkey.

``RegisterHotKey`` is bound to the thread that called it and delivers ``WM_HOTKEY``
to that thread's message queue, so this owns a thread and a message loop of its
own rather than borrowing Qt's.
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes

from .config import Hotkey
from .win32 import WM_HOTKEY, WM_QUIT, kernel32, user32

HOTKEY_ID = 1


class HotkeyError(RuntimeError):
    """The combination could not be registered."""


class HotkeyListener:
    """Calls *callback* every time the user presses the hotkey.

    The callback runs on this listener's thread, not the UI thread — callers are
    expected to hop threads themselves (the Qt front end does it with a signal).
    """

    def __init__(self, hotkey: Hotkey, callback: Callable[[], None]) -> None:
        self._hotkey = hotkey
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    def start(self, timeout: float = 5.0) -> None:
        """Start listening, raising here if registration failed on the thread."""
        self._thread = threading.Thread(target=self._run, name="mlqvoice-hotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise HotkeyError("نخِ کلیدِ میان‌بُر بالا نیامد")
        if self._error is not None:
            raise self._error

    def stop(self) -> None:
        if self._thread_id is not None:
            user32().PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        u = user32()
        self._thread_id = int(kernel32().GetCurrentThreadId())
        try:
            if not u.RegisterHotKey(None, HOTKEY_ID, self._hotkey.modifiers, self._hotkey.vk):
                err = ctypes.get_last_error()
                raise HotkeyError(
                    f"کلیدِ «{self._hotkey}» ثبت نشد (کدِ {err}) — "
                    "احتمالاً برنامه‌ی دیگری همین ترکیب را گرفته است"
                )
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            return

        self._ready.set()
        try:
            msg = wintypes.MSG()
            while True:
                got = u.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got in (0, -1):  # WM_QUIT, or an error we cannot recover from
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self._fire()
        finally:
            u.UnregisterHotKey(None, HOTKEY_ID)

    def _fire(self) -> None:
        # A raising callback must never kill the listener: losing the hotkey
        # would leave the app running with no way to reach it.
        try:
            self._callback()
        except Exception:
            import traceback

            traceback.print_exc()
