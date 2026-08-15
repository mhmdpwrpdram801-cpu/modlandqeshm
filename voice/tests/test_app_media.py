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
from mlqvoice.app import VoiceApp
from mlqvoice.config import Config


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


@pytest.fixture
def app(qt_app, monkeypatch, tmp_path):
    monkeypatch.setattr(inject, "capture_target", lambda: 1234)
    monkeypatch.setattr(inject, "window_title", lambda _hwnd: "Notepad")
    monkeypatch.setattr("mlqvoice.app.user_dictionary_file", lambda: tmp_path / "d.json")
    voice = VoiceApp(Config())
    voice.media = FakeGuard()
    # The browser is never launched here, so pretend it is up.
    monkeypatch.setattr(type(voice.bridge), "browser_alive", lambda _self: True)
    yield voice
    voice.overlay.close()
    voice.overlay.deleteLater()


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

    def test_the_guard_is_off_when_the_setting_is(self, qt_app, monkeypatch, tmp_path):
        monkeypatch.setattr("mlqvoice.app.user_dictionary_file", lambda: tmp_path / "d.json")
        voice = VoiceApp(Config(pause_media=False))
        assert not voice.media.enabled


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

    def test_zero_seconds_turns_it_off(self, qt_app, monkeypatch, tmp_path):
        monkeypatch.setattr(inject, "capture_target", lambda: 1234)
        monkeypatch.setattr(inject, "window_title", lambda _hwnd: "Notepad")
        monkeypatch.setattr("mlqvoice.app.user_dictionary_file", lambda: tmp_path / "d.json")
        voice = VoiceApp(Config(auto_stop_seconds=0))
        monkeypatch.setattr(type(voice.bridge), "browser_alive", lambda _self: True)
        voice.start_recording()
        voice._on_result("سلام", True)
        assert not voice._silence.isActive()
        voice.overlay.close()

    def test_the_configured_number_is_the_one_used(self, qt_app, monkeypatch, tmp_path):
        monkeypatch.setattr(inject, "capture_target", lambda: 1234)
        monkeypatch.setattr(inject, "window_title", lambda _hwnd: "Notepad")
        monkeypatch.setattr("mlqvoice.app.user_dictionary_file", lambda: tmp_path / "d.json")
        voice = VoiceApp(Config(auto_stop_seconds=7))
        monkeypatch.setattr(type(voice.bridge), "browser_alive", lambda _self: True)
        voice.start_recording()
        voice._on_result("سلام", True)
        assert voice._silence.interval() == 7000
        voice.overlay.close()


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
