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

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from mlqvoice import inject
from mlqvoice.app import VoiceApp
from mlqvoice.config import Config
from mlqvoice.media import MediaGuard


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeGuard:
    """Stands in for MediaGuard, recording the calls rather than the keys."""

    def __init__(self):
        self.calls = []
        self.paused = False

    def pause_if_playing(self):
        self.calls.append("pause")
        self.paused = True
        return True

    def resume_if_paused(self):
        self.calls.append("resume") if self.paused else None
        was, self.paused = self.paused, False
        return was


def _shutdown(voice) -> None:
    """Take a VoiceApp down completely, here and now.

    Both halves matter, and the first one cost a Windows CI crash to learn.

    *Stop the timers first.* An armed silence timer outlives the test that
    armed it — four seconds later it fires inside whatever test is running by
    then and calls ``overlay.set_recording(False)`` on an overlay whose C++
    object this teardown already deleted. On Linux PySide6 turns that
    use-after-free into a printed ``RuntimeError``; on Windows it is an access
    violation that takes the whole process down, and the traceback names the
    innocent test that happened to be spinning the event loop at the time.

    *Then flush.* ``deleteLater`` only schedules; the deletion lands on the next
    turn of the event loop, which is to say inside somebody else's test. Draining
    it here keeps this module's mess inside this module — and it takes
    ``sendPostedEvents`` to do it, because ``processEvents`` deliberately skips
    ``DeferredDelete``. The two tests below are what caught that distinction;
    with ``processEvents`` alone the windows were still standing afterwards.
    """
    if getattr(voice, "_torn_down", False):
        return  # a test may have taken it down itself; the fixture still sweeps
    voice._torn_down = True
    voice._silence.stop()
    voice.overlay.set_recording(False)  # stops the pulse timer
    voice.overlay.hide()
    voice.overlay.deleteLater()
    voice.tray.hide()
    QApplication.processEvents()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def make_app(qt_app, monkeypatch, tmp_path):
    """Builds VoiceApps and guarantees every one of them is torn down."""
    monkeypatch.setattr(inject, "capture_target", lambda: 1234)
    monkeypatch.setattr(inject, "window_title", lambda _hwnd: "Notepad")
    monkeypatch.setattr("mlqvoice.app.user_dictionary_file", lambda: tmp_path / "d.json")
    built = []

    def build(**settings):
        voice = VoiceApp(Config(**settings))
        built.append(voice)
        voice.media = FakeGuard()
        # The browser is never launched here, so pretend it is up.
        monkeypatch.setattr(type(voice.bridge), "browser_alive", lambda _self: True)
        return voice

    yield build
    for voice in built:
        _shutdown(voice)


@pytest.fixture
def app(make_app):
    return make_app()


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

    def test_the_silence_timer_is_stopped(self, make_app):
        voice = make_app()
        voice._silence.start(50)
        _shutdown(voice)
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

    def test_the_window_is_really_gone_not_merely_scheduled(self, make_app):
        import shiboken6

        voice = make_app()
        voice.start_recording()
        pulse = voice.overlay._pulse  # grabbed while there is still something there
        assert pulse.isActive()
        _shutdown(voice)
        # The child timer is the honest witness, and it answers the question that
        # matters — a destroyed timer cannot fire into a destroyed window. The
        # overlay's own Python wrapper outlives the C++ object and would say yes.
        assert not shiboken6.Shiboken.isValid(pulse)

    def test_no_overlay_is_left_behind(self, make_app):
        from mlqvoice.ui.overlay import Overlay

        before = sum(isinstance(w, Overlay) for w in QApplication.topLevelWidgets())
        voice = make_app()
        voice.start_recording()
        _shutdown(voice)
        after = sum(isinstance(w, Overlay) for w in QApplication.topLevelWidgets())
        assert after == before
