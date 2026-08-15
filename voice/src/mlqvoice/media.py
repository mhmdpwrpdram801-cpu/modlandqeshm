"""Getting whatever is playing out of the way while you dictate.

The obvious implementation is wrong.  Windows' play/pause key is a *toggle*, so
firing it blindly starts the music when nothing was playing — the opposite of
what was asked for.  So this looks first, and only then acts.

Two rules keep it from ever being annoying:

* **Never resume what we did not pause.**  If the music was already paused, or
  the user paused it themselves mid-dictation, we leave it alone.  The state
  lives in :class:`MediaGuard` for exactly this reason.
* **When we cannot tell, do nothing.**  Detection needs Core Audio; if that is
  unavailable the feature switches itself off rather than guessing and toggling
  at random.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable

from .win32 import IS_WINDOWS, KEYEVENTF_KEYUP, key_input, send_input

log = logging.getLogger(__name__)

#: Virtual-key for the play/pause media key. Applications register for this
#: globally, so it reaches the player whatever window has focus.
VK_MEDIA_PLAY_PAUSE = 0xB3

#: Core Audio session states.
_STATE_ACTIVE = 1


class Unavailable(RuntimeError):
    """Audio detection is not usable here."""


def _sessions():
    """Live audio sessions, or raise :class:`Unavailable`."""
    if not IS_WINDOWS:
        raise Unavailable("تشخیصِ پخشِ صدا فقط روی ویندوز هست")
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise Unavailable(f"pycaw در دسترس نیست: {exc}") from exc
    try:
        return AudioUtilities.GetAllSessions()
    except Exception as exc:  # COM raises all sorts
        raise Unavailable(f"Core Audio جواب نداد: {exc}") from exc


def process_tree(pid: int) -> set[int]:
    """*pid* together with everything it spawned.

    Chrome is a process *family*, and which member of it owns an audio session
    is not something we get to choose.  Asking about the parent alone would let
    our own recogniser window count as somebody else's music.
    """
    found = {pid}
    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil arrives with pycaw
        return found
    # The process may exit while we are walking it; a missing child is not a
    # reason to fall back to a list that would ignore nobody.
    with contextlib.suppress(Exception):
        found |= {child.pid for child in psutil.Process(pid).children(recursive=True)}
    return found


def is_audio_playing(ignore_pids: set[int] | None = None) -> bool:
    """Whether some other program is currently playing sound.

    Session *state* is the signal, not the volume meter: a quiet passage in a
    song still reads as silence on the meter, but the session stays Active. A
    paused player goes Inactive, which is precisely the difference that matters.
    """
    ignore = ignore_pids or set()
    for session in _sessions():
        if session.Process is None:
            continue  # system sounds, not a player
        if session.Process.pid in ignore:
            continue
        if getattr(session, "State", None) == _STATE_ACTIVE:
            return True
    return False


def describe() -> str:
    """One line answering "would pausing work on this machine?", for ``selftest``.

    Deliberately never raises: a machine with no sound card is not a broken
    build, and the two cases have to be told apart in a log rather than merged
    into one failure.
    """
    try:
        sessions = _sessions()
    except Unavailable as exc:
        return f"خاموش ({exc})"
    return f"در دسترس ({len(sessions)} نشستِ صدا)"


def send_play_pause() -> None:
    """Tap the play/pause key."""
    send_input(
        [
            key_input(vk=VK_MEDIA_PLAY_PAUSE),
            key_input(vk=VK_MEDIA_PLAY_PAUSE, flags=KEYEVENTF_KEYUP),
        ]
    )


class MediaGuard:
    """Pauses playback for the duration of a dictation, and puts it back.

    Deliberately conservative: it tracks whether *it* was the one that paused,
    and refuses to resume anything else. Somebody who hits pause themselves
    while the box is open should not find their music restarting.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        ignore_pids: Callable[[], set[int]] | None = None,
    ) -> None:
        self.enabled = enabled
        # A callable, not a set: the recogniser browser is launched after this
        # object exists and gets a new pid every time it is restarted.
        self._ignore = ignore_pids or set
        self._paused_by_us = False
        self._unavailable_logged = False

    @property
    def paused_by_us(self) -> bool:
        return self._paused_by_us

    def pause_if_playing(self) -> bool:
        """Pause playback if something is playing. Returns whether we paused."""
        if not self.enabled or self._paused_by_us:
            return False
        try:
            playing = is_audio_playing(self._ignore())
        except Unavailable as exc:
            self._note_unavailable(exc)
            return False
        if not playing:
            return False
        try:
            send_play_pause()
        except Exception as exc:  # dictation matters more than music
            log.warning("مکثِ پخش نشد: %s", exc)
            return False
        self._paused_by_us = True
        log.info("پخشِ صدا موقتاً متوقف شد")
        return True

    def resume_if_paused(self) -> bool:
        """Resume only if we were the one that paused. Returns whether we did."""
        if not self._paused_by_us:
            return False
        # Cleared before the key goes out, and deliberately not restored if it
        # fails: a retry later would arrive after the user pressed play
        # themselves, and would pause the music instead of resuming it.
        self._paused_by_us = False
        try:
            send_play_pause()
        except Exception as exc:  # never let this break the app
            log.warning("ادامه‌ی پخش نشد: %s", exc)
            return False
        log.info("پخشِ صدا ادامه یافت")
        return True

    def forget(self) -> None:
        """Drop the memory of having paused, without touching playback."""
        self._paused_by_us = False

    def _note_unavailable(self, exc: Unavailable) -> None:
        # Say it once. A warning on every hotkey press is noise nobody reads.
        if not self._unavailable_logged:
            log.info("مکثِ خودکارِ پخش خاموش است: %s", exc)
            self._unavailable_logged = True
