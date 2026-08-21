"""Wiring: hotkey -> recogniser -> pipeline -> overlay -> target window."""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from dataclasses import replace

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, __version__, inject
from .bridge import BrowserNotFound, RecognizerBridge
from .config import Config, ConfigError, load, save
from .correct import Corrector, clean_key, mask, resolve_key
from .hotkey import HotkeyError, HotkeyListener
from .media import MediaGuard, process_tree
from .paths import config_file, learned_file, stats_file, user_dictionary_file
from .text import (
    Options,
    build_lexicon,
    finglish_to_persian,
    learning,
    transform_hits,
)
from .text import stats as usage
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
    #: generation, what the recogniser said, what Gemini made of it.
    corrected = Signal(int, str, str)


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
        # And what the pipeline made of it, so "did the user have to fix this?"
        # can be answered by comparison rather than by asking them.
        self._produced: list[str] = []
        # The guess still on screen when "تمام شد" is pressed is inserted along
        # with everything else, so the comparison that decides "did the user
        # edit this?" has to know about it too.
        self._guess = ""
        self._hits: list[str] = []
        self._spoke_seconds = 0.0
        self._started_at = 0.0

        self.inbox = _Inbox()
        self.inbox.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
        self.inbox.status.connect(self._on_status, Qt.ConnectionType.QueuedConnection)
        self.inbox.corrected.connect(self._on_corrected, Qt.ConnectionType.QueuedConnection)

        # Corrections run one at a time on a worker thread, and the queue is what
        # keeps sentences in the order they were spoken — two calls in flight
        # could finish the other way round and shuffle the user's paragraph.
        # No key means no thread at all: the default build starts nothing.
        self.corrector = Corrector(
            resolve_key(cfg.gemini_key),
            model=cfg.gemini_model,
            timeout=float(cfg.correct_timeout),
        )
        self._corr_gen = 0
        self._corr_pending = 0
        self._corr_q: queue.Queue = queue.Queue()
        self._corr_thread: threading.Thread | None = None
        if self.correcting:
            self._start_correcting()

        self.bridge = RecognizerBridge(
            lang=cfg.lang,
            interim=cfg.interim,
            port=cfg.port,
            browser_path=cfg.browser_path,
            on_result=lambda r: self.inbox.result.emit(r.text, r.final),
            on_status=lambda s, d: self.inbox.status.emit(s, d),
        )

        self.media = MediaGuard(enabled=cfg.pause_media, ignore_pids=self._own_pids)

        # Ends the recording once the user stops talking, so the music comes back
        # without them having to reach for the hotkey again. Started by the first
        # recognition result, never before: someone who presses the hotkey and
        # then thinks for five seconds has not "finished speaking".
        self._silence = QTimer()
        self._silence.setSingleShot(True)
        self._silence.timeout.connect(self._on_silence)

        self.overlay = Overlay()
        if cfg.live_finglish:
            # Typing only. The recogniser's output goes nowhere near this: it is
            # full of deliberate Latin (`commit`, `database`) and transliterating
            # it would undo the glossary. Keystrokes are a different question —
            # somebody typing Finglish has no Persian layout and wants Persian.
            self.overlay.set_transliterator(self._typed_finglish)
        self.overlay.insertRequested.connect(self._insert)
        self.overlay.copyRequested.connect(self._copy)
        self.overlay.toggleRequested.connect(self.toggle)
        self.overlay.dismissed.connect(self._on_dismissed)

        self.tray = Tray(str(self.hotkey))
        self.tray.show_action.triggered.connect(self._show_overlay)
        self.tray.dictionary_action.triggered.connect(self._open_dictionary)
        self.tray.learned_action.triggered.connect(self._open_learned)
        self.tray.apply_learned_action.triggered.connect(self._apply_learned)
        self.tray.config_action.triggered.connect(self._open_config)
        self.tray.key_action.triggered.connect(self._set_key)
        self.tray.quit_action.triggered.connect(self.quit)

        self.listener = HotkeyListener(self.hotkey, self._on_hotkey)

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self.bridge.start()
        # The hotkey is registered *before* Chrome is launched. Cold-starting a
        # browser takes seconds, and with the old order every key press in that
        # window did nothing at all — the listener did not exist yet. Now the
        # key answers immediately, and a press that arrives before the page has
        # connected is held by the bridge until it does.
        self.listener.start()
        self.tray.show()
        self.bridge.launch_browser()
        self.tray.showMessage(
            APP_NAME,
            f"آماده است. برای شروع {self.hotkey} را بزن.",
            self.tray.icon(),
            4000,
        )
        log.info("%s %s ready on %s", APP_NAME, __version__, self.hotkey)

    def quit(self) -> None:
        # Before anything else: quitting mid-dictation must not leave the user's
        # music paused with nothing left running to un-pause it.
        self.media.resume_if_paused()
        # And a timer left armed would fire into a half-torn-down window.
        self._silence.stop()
        self.stop_correcting()
        try:
            self.listener.stop()
        finally:
            self.bridge.stop()
        QApplication.quit()

    def _start_correcting(self) -> None:
        """Bring the correction worker up. Safe to call when it already is."""
        if self._corr_thread is not None:
            return
        self._corr_thread = threading.Thread(
            target=self._correct_loop, name="mlqvoice-correct", daemon=True
        )
        self._corr_thread.start()

    def stop_correcting(self) -> None:
        """Send the correction worker home. Safe to call twice, and on no thread."""
        if self._corr_thread is None:
            return
        self._corr_q.put(None)
        # Short join on purpose: the thread is a daemon and may be mid-request
        # with a timeout of its own. Waiting it out would make quitting feel
        # broken for the sake of a thread the OS is about to reclaim anyway.
        self._corr_thread.join(timeout=1.0)
        self._corr_thread = None

    def _own_pids(self) -> set[int]:
        """Us and the recogniser browser — never mistaken for somebody's music."""
        pids = {os.getpid()}
        browser = self.bridge.browser_pid
        if browser:
            pids |= process_tree(browser)
        return pids

    # -- hotkey ----------------------------------------------------------

    def _on_hotkey(self) -> None:
        # Runs on the listener thread; bounce to the UI thread before touching Qt.
        self.inbox.status.emit("__toggle__", "")

    def toggle(self) -> None:
        self.stop_recording() if self.recording else self.start_recording()

    def start_recording(self) -> None:
        if not self.overlay.isVisible():
            # Must happen before the overlay steals the foreground.
            self.target_hwnd = inject.capture_target(self._own_pids())
            # begin_session, not present: a new dictation starts empty. Closing
            # the box with Esc used to leave the text in the widget, so the next
            # hotkey press showed the previous session's words.
            self._new_session()
            self.overlay.begin_session()
        if not self.bridge.browser_alive():
            self.overlay.set_status("مرورگرِ تشخیصِ گفتار بسته شده — دوباره بازش می‌کنم", bad=True)
            try:
                self.bridge.launch_browser()
            except BrowserNotFound as exc:
                self.overlay.set_status(str(exc), bad=True)
                return
        # Only once we are certain recording is actually starting: pausing on a
        # path that then bails out would leave the music stopped for nothing.
        self.media.pause_if_playing()
        self.recording = True
        self._started_at = time.monotonic()
        self.bridge.start_recording()
        self.overlay.set_recording(True)
        self.tray.set_recording(True)

    def stop_recording(self) -> None:
        if self._started_at:
            self._spoke_seconds += time.monotonic() - self._started_at
            self._started_at = 0.0
        self.recording = False
        self._silence.stop()
        self.bridge.stop_recording()
        self.overlay.set_recording(False)
        self.tray.set_recording(False)
        # Every way out of recording passes through here — the hotkey, the
        # button, "بنویس", Esc, a fatal recogniser error — which is what makes
        # this the one place playback has to be handed back.
        self.media.resume_if_paused()

    def _on_silence(self) -> None:
        if not self.recording:
            return
        self.stop_recording()
        self.overlay.set_status("سکوت — ضبط تمام شد")

    # -- recogniser ------------------------------------------------------

    @property
    def correcting(self) -> bool:
        return self.cfg.correct and self.corrector.enabled

    def _on_result(self, text: str, final: bool) -> None:
        # Interim guesses count as speech: Chrome emits them continuously while
        # a sentence is being spoken, so they are the evidence that the silence
        # has not started yet. Restarting on finals alone would cut off anyone
        # mid-sentence.
        self._restart_silence_timer()
        if final:
            if self.correcting:
                # Held back rather than shown and then rewritten: the box is
                # also the user's edit buffer, and text that changes under a
                # cursor is worse than text that arrives a second late. The
                # interim guess stays on screen meanwhile, so nothing looks
                # stuck.
                self._corr_pending += 1
                self._corr_q.put((self._corr_gen, text))
                return
            self._commit_final(text, text)
            return
        cleaned, _ = transform_hits(text, self.lexicon, self.opts)
        if not cleaned:
            return
        self._guess = cleaned
        self.overlay.set_interim(cleaned)

    def _commit_final(self, heard: str, corrected: str) -> None:
        """Put one finished sentence in the box.

        *heard* is what the recogniser said and *corrected* is what goes on
        screen. They are recorded separately on purpose: the learning layer
        earns its entries from Google's mistakes, and crediting Gemini's fix to
        the user would quietly teach it nothing.
        """
        cleaned, hits = transform_hits(corrected, self.lexicon, self.opts)
        if not cleaned:
            return
        self._heard.append(heard.strip())
        # Finals only: interim guesses are rewritten continuously, and
        # counting them would report one sentence as twenty dictionary hits.
        self._produced.append(cleaned)
        self._hits.extend(hits)
        self._guess = ""
        self.overlay.append_final(cleaned)

    def _correct_loop(self) -> None:
        while True:
            item = self._corr_q.get()
            if item is None:
                return
            gen, heard = item
            # Corrector.correct never raises; it hands back the original on any
            # failure. Wrapping it again would only hide a real bug in here.
            self.inbox.corrected.emit(gen, heard, self.corrector.correct(heard))

    def _on_corrected(self, gen: int, heard: str, corrected: str) -> None:
        self._corr_pending -= 1
        if gen != self._corr_gen:
            return  # belongs to a dictation the user has already finished
        self._commit_final(heard, corrected)

    def _await_corrections(self) -> None:
        """Let anything still in flight land before the text is used.

        Without this, pressing "تمام شد" while the last sentence is still with
        Gemini would insert everything *except* that sentence — the one failure
        this whole feature is not allowed to have. The wait is bounded by the
        corrector's own timeout, and the queue only ever holds finished
        sentences, so the worst case is one round trip.
        """
        if not self._corr_pending:
            return
        self.overlay.set_status("در حالِ تصحیح…")
        deadline = time.monotonic() + float(self.cfg.correct_timeout) + 2.0
        while self._corr_pending > 0 and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)
        if self._corr_pending > 0:
            # Give up counting rather than block forever; the sentences that did
            # arrive are already in the box and will be inserted.
            log.warning("correction did not return in time; inserting what we have")
            self._corr_pending = 0

    def _restart_silence_timer(self) -> None:
        if not self.recording or self.cfg.auto_stop_seconds <= 0:
            return
        self._silence.start(self.cfg.auto_stop_seconds * 1000)

    def _on_status(self, state: str, detail: str) -> None:
        if state == "__toggle__":
            self.toggle()
            return
        if state == "error":
            # These three are dead ends: the page has stopped trying, so leaving
            # the app "recording" would show a pulsing dot next to a microphone
            # nobody is listening to — and would hold the user's music paused.
            if detail in ("not-allowed", "service-not-allowed", "unreachable"):
                self.stop_recording()
            # After the stop, never before: set_recording(False) writes "متوقف"
            # into the same label, so the message explaining *why* was being
            # wiped a line after it was set. The microphone-permission error has
            # been invisible this whole time for exactly that reason — the user
            # saw a box that just stopped, with no hint that they had to grant
            # anything.
            self.overlay.set_status(_explain(detail), bad=True)
        elif state == "listening" and self.recording:
            self.overlay.set_recording(True)
        elif state == "unsupported":
            self.overlay.set_status("این مرورگر Web Speech API ندارد — کروم لازم است", bad=True)

    # -- actions ---------------------------------------------------------

    def _show_overlay(self) -> None:
        if self.overlay.isVisible():
            self.overlay.present()
            return
        self.target_hwnd = inject.capture_target(self._own_pids())
        self._new_session()
        self.overlay.begin_session()

    def _insert(self, text: str) -> None:
        if self.recording:
            self.stop_recording()
        if self._corr_pending:
            # Stop first, then wait: otherwise a sentence spoken during the wait
            # would start another correction and the wait would chase its tail.
            self._await_corrections()
            text = self.overlay.text()
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
        self._count(text)
        if self.cfg.close_after_insert:
            self.overlay.clear()
        else:
            self.overlay.present()

    def _new_session(self) -> None:
        """Forget the previous dictation entirely — text, hits and clock."""
        self._heard.clear()
        self._produced.clear()
        self._guess = ""
        self._hits.clear()
        self._spoke_seconds = 0.0
        self._started_at = 0.0
        # A correction still in flight belongs to the dictation that just ended.
        # Bumping the generation is what stops it landing in this one — the
        # worker cannot be called back, only ignored.
        self._corr_gen += 1
        self._corr_pending = 0

    def _count(self, inserted: str) -> None:
        """Tally one dictation, so the dictionary can be judged on evidence.

        Never fatal, like the learning file: a lost count is nothing next to a
        lost sentence. Numbers only — see :mod:`mlqvoice.text.stats` for what is
        deliberately not written here.
        """
        if not self.cfg.stats:
            return
        produced = " ".join([*self._produced, self._guess] if self._guess else self._produced)
        try:
            usage.record(
                stats_file(),
                words=len(inserted.split()),
                # Whitespace-insensitive: re-wrapping a line is not a correction,
                # and counting it as one would quietly depress the number this
                # whole file exists to report.
                edited=" ".join(produced.split()) != " ".join(inserted.split()),
                seconds=round(self._spoke_seconds),
                terms=list(self._hits),
            )
        except OSError as exc:
            log.warning("ثبتِ آمار نشد: %s", exc)

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

    def _typed_finglish(self, word: str) -> str:
        """One typed word, transliterated — or handed straight back.

        The same skip-list the button uses, so code and glossary output survive:
        `app.py`, `user_id` and `commit` are returned untouched.
        """
        return finglish_to_persian(word, skip=self.lexicon.outputs())

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

    def _apply_learned(self) -> None:
        """Accept what the app learned, in one click and with no shell.

        This is the local, key-free half of getting fewer mistakes: the app
        already watches what you fix by hand before pressing «بنویس» and keeps
        the difference. Until now the only way to *accept* those suggestions was
        ``mlqvoice learn --apply`` — a command that, on the installed build,
        could not even be reached (§۵.۵). So the feature existed and nobody
        could use it.
        """
        from PySide6.QtWidgets import QMessageBox

        stored = learning.load(learned_file())
        if not stored:
            self.tray.showMessage(
                APP_NAME,
                "هنوز چیزی یاد نگرفته. متن را قبل از «بنویس» ویرایش کن تا یاد بگیرد.",
                self.tray.icon(),
                5000,
            )
            return

        pending = sum(len(forms) for forms in learning.as_dictionary(stored).values())
        answer = QMessageBox.question(
            None,
            "افزودن به دیکشنری",
            f"{_fa(pending)} شکلِ گفتاری به دیکشنریِ خودت اضافه شود؟\n"
            "پیشنهادها پاک نمی‌شوند و هر وقت خواستی می‌توانی خودِ فایل را ویرایش کنی.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            # The safe option is the focused one, so a stray Enter changes
            # nothing — the same rule the panel learned the hard way.
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            added = learning.apply_to_dictionary(user_dictionary_file(), stored)
        except learning.DictionaryUnreadable as exc:
            # Never silently: a refusal the user cannot see is the same as the
            # write having failed for no reason (OPS-03).
            self.tray.showMessage(
                APP_NAME, f"دیکشنریِ تو دست‌نخورده ماند: {exc}", self.tray.icon(), 8000
            )
            return

        # Rebuilt here rather than at the next start: a dictionary entry that
        # only works tomorrow is indistinguishable from one that did not save.
        self.lexicon = build_lexicon(
            glossary=self.cfg.glossary,
            punctuation=self.cfg.punctuation,
            user_file=user_dictionary_file(),
        )
        log.info("applied %d learned forms; lexicon now %d entries", added, len(self.lexicon))
        self.tray.showMessage(
            APP_NAME,
            f"{_fa(added)} شکل اضافه شد و همین حالا فعال است."
            if added
            else "چیزی تازه نبود — همه‌شان از قبل در دیکشنری بودند.",
            self.tray.icon(),
            5000,
        )

    def _open_config(self) -> None:
        path = config_file()
        if not path.exists():
            save(self.cfg, path)
        _open_in_editor(path)

    def _set_key(self) -> None:
        """Paste the Gemini key into a box, rather than into a shell.

        ``mlqvoice key …`` does the same thing and stays the documented way, but
        it asks someone to open PowerShell, know the program is reachable by
        name, and read output back from a windowed process. Every one of those
        is a place to get stuck, and the tray menu is already open.
        """
        from PySide6.QtWidgets import QInputDialog, QLineEdit

        current = resolve_key(self.cfg.gemini_key)
        text, ok = QInputDialog.getText(
            None,
            "کلیدِ تصحیح",
            "کلیدِ Gemini را اینجا بچسبان.\n"
            "کلیدِ رایگان: aistudio.google.com ← Get API key\n"
            f"کلیدِ فعلی: {mask(current)}\n"
            "(خالی بگذار و تأیید کن تا تصحیح خاموش شود)",
            QLineEdit.EchoMode.Normal,
            "",
        )
        if not ok:
            return
        if not text.strip():
            self._apply_key("")
            return
        try:
            key = clean_key(text)
        except ValueError as exc:
            # A tray balloon, not a modal: the box is gone by now and a second
            # dialog on top of nothing is how people lose what they pasted.
            self.tray.showMessage(APP_NAME, str(exc), self.tray.icon(), 5000)
            return
        self._apply_key(key)

    def _apply_key(self, key: str) -> None:
        """Store the key and start — or stop — correcting, without a restart.

        Restarting would be the easy answer and the wrong one: the app is
        started from the Start menu, so "close it and open it again" is three
        steps the user has to be told, and the state it would rebuild is exactly
        two fields.
        """
        self.cfg = replace(self.cfg, gemini_key=key)
        save(self.cfg)
        self.corrector.api_key = key
        if self.correcting:
            self._start_correcting()
            note = f"تصحیح روشن شد — کلید {mask(key)}"
        else:
            self.stop_correcting()
            # A key that was saved and still does nothing needs to say why,
            # or the next report is "I set the key and it did not work".
            note = (
                "کلید ذخیره شد، ولی در تنظیمات correct=false است."
                if key
                else "کلید پاک شد — تصحیح خاموش است."
            )
        log.info("correction key updated; correcting=%s", self.correcting)
        self.tray.showMessage(APP_NAME, note, self.tray.icon(), 4000)


def _fa(number: int) -> str:
    """A count the way it is read here. A Latin digit in a Persian sentence is
    a small thing that makes the sentence look like it came from somewhere else."""
    from .text.normalize import to_persian_digits

    return to_persian_digits(str(number))


def _explain(error: str) -> str:
    return {
        "not-allowed": "دسترسی به میکروفون داده نشد",
        "service-not-allowed": "سرویسِ تشخیصِ گفتار در دسترس نیست",
        "network": "شبکه قطع است — تشخیصِ گفتارِ گوگل اینترنت لازم دارد",
        "unreachable": "سرویسِ تشخیصِ گفتار جواب نداد — اینترنت یا VPN را چک کن و دوباره بزن",
        "audio-capture": "میکروفونی پیدا نشد",
    }.get(error, f"خطای تشخیصِ گفتار: {error}")


def _open_in_editor(path) -> None:
    os.startfile(path)


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
