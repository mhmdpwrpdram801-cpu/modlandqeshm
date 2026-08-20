"""Fixtures shared by the tests that build a whole ``VoiceApp``.

They live here rather than in one test file because two of them now need the
same thing, and a second copy of a teardown this fiddly would drift — the first
version of it caused an access violation on Windows CI, in a completely
unrelated test file.
"""

import os

import pytest

# Note: conftest is imported for *every* run in this directory, so this reaches
# the end-to-end test too, which needs a real window. That file undoes it for
# itself — see the comment there for why it cannot be done from the workflow.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 نصب نیست")

from PySide6.QtCore import QEvent
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
def shutdown():
    """The teardown, handed to tests that want to take an app down themselves."""
    return _shutdown


@pytest.fixture
def make_app(qt_app, monkeypatch, tmp_path):
    """Builds VoiceApps and guarantees every one of them is torn down."""
    monkeypatch.setattr(inject, "capture_target", lambda *_a: 1234)
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
