"""The wiring: when the app pauses playback, and when it hands it back.

``test_media.py`` proves the guard's own state machine. What is left — and what
actually reaches the user — is whether every way out of a recording resumes.
There are five of them (hotkey, the box's button, "بنویس", Esc, a fatal
recogniser error) and the guard is useless if even one forgets.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 نصب نیست")

from PySide6.QtWidgets import QApplication

from mlqvoice import inject
from mlqvoice.media import MediaGuard


class TestPausesAndResumes:
    def test_recording_pauses_playback(self, app):
        app.start_recording()
        assert app.media.calls == ["pause"]

    def test_the_hotkey_a_second_time_resumes_it(self, app):
        app.start_recording()
        app.toggle()
        assert app.media.calls == ["pause", "resume"]

    def test_inserting_the_text_resumes_it(self, app, monkeypatch):
        monkeypatch.setattr(inject, "insert", lambda *a, **k: None)
        app.start_recording()
        app._insert("سلام")
        assert app.media.calls == ["pause", "resume"]

    def test_a_failed_insert_still_resumes_it(self, app, monkeypatch):
        # The text is not lost and the box comes back — but the music must not
        # stay stopped just because the paste failed.
        def boom(*_a, **_k):
            raise inject.InjectError("پنجره فوکوس نگرفت")

        monkeypatch.setattr(inject, "insert", boom)
        app.start_recording()
        app._insert("سلام")
        assert app.media.calls == ["pause", "resume"]

    def test_closing_the_box_resumes_it(self, app):
        app.start_recording()
        app.overlay.dismiss()
        assert app.media.calls == ["pause", "resume"]

    def test_a_fatal_recogniser_error_resumes_it(self, app):
        app.start_recording()
        app._on_status("error", "not-allowed")
        assert app.media.calls == ["pause", "resume"]

    def test_the_page_giving_up_on_the_network_resumes_it_too(self, app):
        # When the page stops retrying, nothing is listening any more. Staying
        # "recording" would pulse a dot at a dead microphone and hold the music
        # paused with no way back short of quitting.
        app.start_recording()
        app._on_status("error", "unreachable")
        assert not app.recording
        assert app.media.calls == ["pause", "resume"]

    def test_and_the_box_explains_it_in_persian(self, app):
        app.start_recording()
        app._on_status("error", "unreachable")
        assert "VPN" in app.overlay._state.text()

    def test_the_microphone_refusal_is_visible_too(self, app):
        # This one was broken long before the media work: the message was set
        # and then stop_recording() wrote "متوقف" over it a line later, so the
        # user saw the box stop with no hint that permission was the problem.
        app.start_recording()
        app._on_status("error", "not-allowed")
        assert "میکروفون" in app.overlay._state.text()

    def test_quitting_mid_dictation_resumes_it(self, app, monkeypatch):
        # Nothing is left running to un-pause it afterwards, so this is the one
        # path where forgetting would leave the user's music stopped for good.
        monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: None))
        monkeypatch.setattr(type(app.listener), "stop", lambda _self: None)
        monkeypatch.setattr(type(app.bridge), "stop", lambda _self: None)
        app.start_recording()
        app.quit()
        assert app.media.calls == ["pause", "resume"]

    def test_no_browser_means_no_pause(self, app, monkeypatch):
        # start_recording bails out here; pausing first would stop the music for
        # a dictation that never began.
        from mlqvoice.bridge import BrowserNotFound

        monkeypatch.setattr(type(app.bridge), "browser_alive", lambda _self: False)
        monkeypatch.setattr(
            type(app.bridge),
            "launch_browser",
            lambda _self: (_ for _ in ()).throw(BrowserNotFound("کروم نیست")),
        )
        app.start_recording()
        assert app.media.calls == []

    def test_the_guard_is_off_when_the_setting_is(self, make_app):
        voice = make_app(pause_media=False)
        # make_app swaps in the fake, so ask the real one the setting produced.
        assert not MediaGuard(enabled=voice.cfg.pause_media).enabled


class TestSilenceStopsIt:
    def test_speaking_starts_the_countdown(self, app):
        app.start_recording()
        assert not app._silence.isActive()
        app._on_result("سلام", False)
        assert app._silence.isActive()

    def test_nothing_counts_down_before_you_speak(self, app):
        # Someone who presses the hotkey and then thinks for five seconds has
        # not "finished speaking" — cutting them off there would be a bug.
        app.start_recording()
        assert not app._silence.isActive()

    def test_interim_guesses_keep_it_alive(self, app):
        # Chrome emits these continuously mid-sentence; ignoring them would stop
        # the recording in the middle of a long one.
        app.start_recording()
        app._on_result("سلام", True)
        app._silence.stop()
        app._on_result("چطوری", False)
        assert app._silence.isActive()

    def test_the_timeout_stops_the_recording_and_resumes_playback(self, app):
        app.start_recording()
        app._on_result("سلام", True)
        app._on_silence()
        assert not app.recording
        assert app.media.calls == ["pause", "resume"]

    def test_and_says_why_it_stopped(self, app):
        app.start_recording()
        app._on_result("سلام", True)
        app._on_silence()
        assert "سکوت" in app.overlay._state.text()

    def test_stopping_cancels_the_countdown(self, app):
        # Otherwise it would fire into an already-stopped session and, with the
        # box reopened by then, stop the *next* recording early.
        app.start_recording()
        app._on_result("سلام", False)
        app.stop_recording()
        assert not app._silence.isActive()

    def test_a_late_timeout_after_stopping_says_nothing(self, app):
        # Qt can deliver a timeout that was already queued when the recording
        # ended; announcing "سکوت" over whatever the box is showing would be a
        # lie about a session that is already over.
        app.start_recording()
        app.stop_recording()
        before = app.overlay._state.text()
        app._on_silence()
        assert app.overlay._state.text() == before

    def test_zero_seconds_turns_it_off(self, make_app):
        voice = make_app(auto_stop_seconds=0)
        voice.start_recording()
        voice._on_result("سلام", True)
        assert not voice._silence.isActive()

    def test_the_configured_number_is_the_one_used(self, make_app):
        voice = make_app(auto_stop_seconds=7)
        voice.start_recording()
        voice._on_result("سلام", True)
        assert voice._silence.interval() == 7000


class TestOwnProcessesAreIgnored:
    def test_our_own_pid_is_on_the_list(self, app):
        assert os.getpid() in app._own_pids()

    def test_the_browser_is_too_once_it_is_running(self, app, monkeypatch):
        monkeypatch.setattr(type(app.bridge), "browser_pid", property(lambda _self: 4321))
        monkeypatch.setattr("mlqvoice.app.process_tree", lambda pid: {pid, pid + 1})
        pids = app._own_pids()
        assert {4321, 4322} <= pids

    def test_a_browser_that_is_not_running_adds_nothing(self, app):
        # browser_pid is 0 here; treating that as a real pid would silently
        # ignore whichever process happened to be pid 0.
        assert 0 not in app._own_pids()


class TestTeardownLeavesNothingRunning:
    """The Windows CI crash: an armed timer outliving the window it points at.

    It surfaced as an access violation inside ``test_overlay.py`` — a file this
    change never touched — because that is simply where the event loop happened
    to be spinning four seconds later. The rule the failure teaches: a test that
    arms a timer owns switching it off, and ``deleteLater`` is not cleanup until
    something drains the event loop.
    """

    def test_the_silence_timer_is_stopped(self, make_app, shutdown):
        voice = make_app()
        voice._silence.start(50)
        shutdown(voice)
        assert not voice._silence.isActive()

    def test_quitting_disarms_the_silence_timer(self, app, monkeypatch):
        # quit() does not go through stop_recording, so it needs its own.
        monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: None))
        monkeypatch.setattr(type(app.listener), "stop", lambda _self: None)
        monkeypatch.setattr(type(app.bridge), "stop", lambda _self: None)
        app.start_recording()
        app._on_result("سلام", True)
        app.quit()
        assert not app._silence.isActive()

    def test_the_window_is_really_gone_not_merely_scheduled(self, make_app, shutdown):
        import shiboken6

        voice = make_app()
        voice.start_recording()
        pulse = voice.overlay._pulse  # grabbed while there is still something there
        assert pulse.isActive()
        shutdown(voice)
        # The child timer is the honest witness, and it answers the question that
        # matters — a destroyed timer cannot fire into a destroyed window. The
        # overlay's own Python wrapper outlives the C++ object and would say yes.
        assert not shiboken6.Shiboken.isValid(pulse)

    def test_no_overlay_is_left_behind(self, make_app, shutdown):
        from mlqvoice.ui.overlay import Overlay

        before = sum(isinstance(w, Overlay) for w in QApplication.topLevelWidgets())
        voice = make_app()
        voice.start_recording()
        shutdown(voice)
        after = sum(isinstance(w, Overlay) for w in QApplication.topLevelWidgets())
        assert after == before


class TestOurOwnWindowIsNeverTheDestination:
    """From a photo the owner sent: the box said «مقصد: mlqvoice — تشخیص گفتار».

    Chrome steals the foreground for a moment while it cold-starts. A hotkey
    press in that window captured *it* as the destination, so "تمام شد" would
    have typed the sentence into an off-screen window the user cannot see —
    and the box announced that as if it were a normal destination.
    """

    def test_a_window_owned_by_us_is_refused(self, monkeypatch):
        from mlqvoice import inject

        monkeypatch.setattr(inject, "user32", lambda: _FakeUser32(foreground=77))
        monkeypatch.setattr(inject, "window_pid", lambda _hwnd: 4321)
        assert inject.capture_target({4321, 999}) == 0

    def test_somebody_else_window_is_kept(self, monkeypatch):
        from mlqvoice import inject

        monkeypatch.setattr(inject, "user32", lambda: _FakeUser32(foreground=77))
        monkeypatch.setattr(inject, "window_pid", lambda _hwnd: 5555)
        assert inject.capture_target({4321}) == 77

    def test_with_no_reject_list_nothing_is_refused(self, monkeypatch):
        from mlqvoice import inject

        monkeypatch.setattr(inject, "user32", lambda: _FakeUser32(foreground=77))
        assert inject.capture_target() == 77

    def test_the_app_passes_its_own_pids_in(self, app, monkeypatch):
        # The wiring, not just the helper: the guard is useless if the app never
        # tells it which processes are ours.
        from mlqvoice import inject

        seen = []
        monkeypatch.setattr(inject, "capture_target", lambda pids=None: seen.append(pids) or 0)
        app.overlay.hide()
        app.start_recording()
        assert seen and os.getpid() in seen[0]


class _FakeUser32:
    def __init__(self, foreground: int):
        self._foreground = foreground

    def GetForegroundWindow(self):  # mirrors the Win32 name
        return self._foreground
