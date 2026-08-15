"""Wiring: hotkey -> recogniser -> pipeline -> overlay -> target window."""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, __version__, inject
from .bridge import BrowserNotFound, RecognizerBridge
from .config import Config, ConfigError, load, save
from .hotkey import HotkeyError, HotkeyListener
from .paths import config_file, learned_file, user_dictionary_file
from .text import Options, build_lexicon, learning, transform
from .ui.overlay import Overlay
from .ui.tray import Tray
from .win32 import IS_WINDOWS

log = logging.getLogger(__name__)

DEFAULT_DICTIONARY = """{
  "note": "کلید = چیزی که نوشته می‌شود، فهرست = شکل‌هایی که ممکن است بگویی.",
  "terms": {
    "kubectl": ["کیوب سی تی ال"],
    "nginx": ["ان جین ایکس"]
  },
  "symbols": [
    { "say": ["تیلدا"], "text": "~", "attach": "both" }
  ]
}
"""


class _Inbox(QObject):
    """Moves bridge callbacks off their HTTP thread and onto the UI thread."""

    result = Signal(str, bool)
    status = Signal(str, str)


class VoiceApp:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.hotkey = cfg.validate()
        self.opts = Options(
            digits=cfg.digits,
            zwnj=cfg.zwnj,
            glossary=cfg.glossary,
            punctuation=cfg.punctuation,
        )
        self.lexicon = build_lexicon(
            glossary=cfg.glossary,
            punctuation=cfg.punctuation,
            user_file=user_dictionary_file(),
        )

        self.recording = False
        self.target_hwnd = 0
        # What the recogniser actually said, kept so that the difference between
        # it and what the user finally inserted can become a dictionary entry.
        self._heard: list[str] = []

        self.inbox = _Inbox()
        self.inbox.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
        self.inbox.status.connect(self._on_status, Qt.ConnectionType.QueuedConnection)

        self.bridge = RecognizerBridge(
            lang=cfg.lang,
            interim=cfg.interim,
            port=cfg.port,
            browser_path=cfg.browser_path,
            on_result=lambda r: self.inbox.result.emit(r.text, r.final),
            on_status=lambda s, d: self.inbox.status.emit(s, d),
        )

        self.overlay = Overlay()
        self.overlay.insertRequested.connect(self._insert)
        self.overlay.copyRequested.connect(self._copy)
        self.overlay.toggleRequested.connect(self.toggle)
        self.overlay.dismissed.connect(self._on_dismissed)

        self.tray = Tray(str(self.hotkey))
        self.tray.show_action.triggered.connect(self._show_overlay)
        self.tray.dictionary_action.triggered.connect(self._open_dictionary)
        self.tray.learned_action.triggered.connect(self._open_learned)
        self.tray.config_action.triggered.connect(self._open_config)
        self.tray.quit_action.triggered.connect(self.quit)

        self.listener = HotkeyListener(self.hotkey, self._on_hotkey)

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self.bridge.start()
        self.bridge.launch_browser()
        self.listener.start()
        self.tray.show()
        self.tray.showMessage(
            APP_NAME,
            f"آماده است. برای شروع {self.hotkey} را بزن.",
            self.tray.icon(),
            4000,
        )
        log.info("%s %s ready on %s", APP_NAME, __version__, self.hotkey)

    def quit(self) -> None:
        try:
            self.listener.stop()
        finally:
            self.bridge.stop()
        QApplication.quit()

    # -- hotkey ----------------------------------------------------------

    def _on_hotkey(self) -> None:
        # Runs on the listener thread; bounce to the UI thread before touching Qt.
        self.inbox.status.emit("__toggle__", "")

    def toggle(self) -> None:
        self.stop_recording() if self.recording else self.start_recording()

    def start_recording(self) -> None:
        if not self.overlay.isVisible():
            # Must happen before the overlay steals the foreground.
            self.target_hwnd = inject.capture_target()
            # begin_session, not present: a new dictation starts empty. Closing
            # the box with Esc used to leave the text in the widget, so the next
            # hotkey press showed the previous session's words.
            self._heard.clear()
            self.overlay.begin_session(inject.window_title(self.target_hwnd))
        if not self.bridge.browser_alive():
            self.overlay.set_status("مرورگرِ تشخیصِ گفتار بسته شده — دوباره بازش می‌کنم", bad=True)
            try:
                self.bridge.launch_browser()
            except BrowserNotFound as exc:
                self.overlay.set_status(str(exc), bad=True)
                return
        self.recording = True
        self.bridge.start_recording()
        self.overlay.set_recording(True)
        self.tray.set_recording(True)

    def stop_recording(self) -> None:
        self.recording = False
        self.bridge.stop_recording()
        self.overlay.set_recording(False)
        self.tray.set_recording(False)

    # -- recogniser ------------------------------------------------------

    def _on_result(self, text: str, final: bool) -> None:
        cleaned = transform(text, self.lexicon, self.opts)
        if not cleaned:
            return
        if final:
            self._heard.append(text.strip())
            self.overlay.append_final(cleaned)
        else:
            self.overlay.set_interim(cleaned)

    def _on_status(self, state: str, detail: str) -> None:
        if state == "__toggle__":
            self.toggle()
            return
        if state == "error":
            self.overlay.set_status(_explain(detail), bad=True)
            if detail in ("not-allowed", "service-not-allowed"):
                self.stop_recording()
        elif state == "listening" and self.recording:
            self.overlay.set_recording(True)
        elif state == "unsupported":
            self.overlay.set_status("این مرورگر Web Speech API ندارد — کروم لازم است", bad=True)

    # -- actions ---------------------------------------------------------

    def _show_overlay(self) -> None:
        if self.overlay.isVisible():
            self.overlay.present()
            return
        self.target_hwnd = inject.capture_target()
        self._heard.clear()
        self.overlay.begin_session(inject.window_title(self.target_hwnd))

    def _insert(self, text: str) -> None:
        if self.recording:
            self.stop_recording()
        self.overlay.hide()  # our own window must not hold the foreground
        try:
            inject.insert(
                self.target_hwnd,
                text,
                mode=self.cfg.insert_mode,
                restore_clipboard=self.cfg.restore_clipboard,
            )
        except inject.InjectError as exc:
            self.overlay.present()
            self.overlay.set_status(str(exc), bad=True)
            return
        self._learn_from(text)
        if self.cfg.close_after_insert:
            self.overlay.clear()
        else:
            self.overlay.present()

    def _learn_from(self, inserted: str) -> None:
        """Turn the user's hand edits into proposed dictionary entries.

        Never fatal: this is a convenience, and losing a suggestion is nothing
        next to losing the text the user just dictated.
        """
        if not self.cfg.learn or not self._heard:
            return
        try:
            learning.record(
                learned_file(), " ".join(self._heard), inserted, self.lexicon, self.opts
            )
        except OSError as exc:
            log.warning("ثبتِ پیشنهادِ دیکشنری نشد: %s", exc)

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.overlay.set_status("کپی شد")

    def _on_dismissed(self) -> None:
        if self.recording:
            self.stop_recording()

    def _open_dictionary(self) -> None:
        path = user_dictionary_file()
        if not path.exists():
            path.write_text(DEFAULT_DICTIONARY, encoding="utf-8")
        _open_in_editor(path)

    def _open_learned(self) -> None:
        path = learned_file()
        if not path.exists():
            self.tray.showMessage(
                APP_NAME,
                "هنوز چیزی یاد نگرفته. متن را قبل از «بنویس» ویرایش کن.",
                self.tray.icon(),
                4000,
            )
            return
        _open_in_editor(path)

    def _open_config(self) -> None:
        path = config_file()
        if not path.exists():
            save(self.cfg, path)
        _open_in_editor(path)


def _explain(error: str) -> str:
    return {
        "not-allowed": "دسترسی به میکروفون داده نشد",
        "service-not-allowed": "سرویسِ تشخیصِ گفتار در دسترس نیست",
        "network": "شبکه قطع است — تشخیصِ گفتارِ گوگل اینترنت لازم دارد",
        "audio-capture": "میکروفونی پیدا نشد",
    }.get(error, f"خطای تشخیصِ گفتار: {error}")


def _open_in_editor(path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", str(path)])


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    qt = QApplication(sys.argv)
    qt.setApplicationName(APP_NAME)
    qt.setQuitOnLastWindowClosed(False)  # the overlay closing must not end the app

    if not IS_WINDOWS:
        QMessageBox.critical(None, APP_NAME, "این برنامه فقط روی ویندوز اجرا می‌شود.")
        return 2

    try:
        cfg = load()
    except ConfigError as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 2

    if cfg._unknown:
        log.warning("تنظیماتِ ناشناخته نادیده گرفته شد: %s", ", ".join(cfg._unknown))

    try:
        app = VoiceApp(cfg)
        app.start()
    except (ConfigError, HotkeyError, BrowserNotFound) as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 2

    return qt.exec()
