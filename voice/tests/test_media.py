"""Pausing whatever is playing while you dictate.

The whole feature hangs on one Windows fact: the play/pause key is a *toggle*.
Sending it without knowing what is going on turns "pause my music" into "start
playing music at a random moment", which is worse than doing nothing at all.

So these tests are almost entirely about restraint — the cases where the guard
must keep its hands off — rather than about the happy path.
"""

import pytest

from mlqvoice import media
from mlqvoice.media import MediaGuard, Unavailable, is_audio_playing
from mlqvoice.win32 import IS_WINDOWS, KEYEVENTF_KEYUP


class FakeSession:
    def __init__(self, state, pid=None):
        self.State = state
        self.Process = None if pid is None else type("P", (), {"pid": pid})()


@pytest.fixture
def taps(monkeypatch):
    """Record every play/pause key sent, instead of sending it."""
    sent = []
    monkeypatch.setattr(media, "send_play_pause", lambda: sent.append("tap"))
    return sent


def playing(monkeypatch, answer):
    """Make detection return *answer*, or raise it if it is an exception."""

    def fake(_ignore=None):
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(media, "is_audio_playing", fake)


class TestDetection:
    def test_an_active_session_counts_as_playing(self, monkeypatch):
        monkeypatch.setattr(media, "_sessions", lambda: [FakeSession(1, pid=42)])
        assert is_audio_playing()

    def test_a_paused_player_does_not(self, monkeypatch):
        # State 0 is Inactive — the player is open but stopped. Sending the key
        # here would *start* the music, which is the bug this guards against.
        monkeypatch.setattr(media, "_sessions", lambda: [FakeSession(0, pid=42)])
        assert not is_audio_playing()

    def test_sessions_without_a_process_are_skipped(self, monkeypatch):
        # System sounds have no owning process and nothing to pause.
        monkeypatch.setattr(media, "_sessions", lambda: [FakeSession(1, pid=None)])
        assert not is_audio_playing()

    def test_our_own_processes_do_not_count(self, monkeypatch):
        # Our recogniser Chrome holding an audio session must not read as the
        # user's music, or every hotkey press would toggle their player.
        monkeypatch.setattr(media, "_sessions", lambda: [FakeSession(1, pid=99)])
        assert not is_audio_playing({99})

    def test_one_player_among_several_is_enough(self, monkeypatch):
        monkeypatch.setattr(
            media,
            "_sessions",
            lambda: [FakeSession(0, pid=1), FakeSession(1, pid=2), FakeSession(0, pid=3)],
        )
        assert is_audio_playing()

    @pytest.mark.skipif(IS_WINDOWS, reason="روی ویندوز واقعاً در دسترس است")
    def test_off_windows_it_says_so_rather_than_guessing(self):
        with pytest.raises(Unavailable):
            is_audio_playing()


class TestPause:
    def test_pauses_when_something_is_playing(self, monkeypatch, taps):
        playing(monkeypatch, True)
        guard = MediaGuard()
        assert guard.pause_if_playing()
        assert taps == ["tap"]
        assert guard.paused_by_us

    def test_stays_quiet_when_nothing_is_playing(self, monkeypatch, taps):
        playing(monkeypatch, False)
        guard = MediaGuard()
        assert not guard.pause_if_playing()
        assert taps == []

    def test_disabled_never_touches_anything(self, monkeypatch, taps):
        playing(monkeypatch, True)
        guard = MediaGuard(enabled=False)
        assert not guard.pause_if_playing()
        assert taps == []

    def test_a_second_press_does_not_pause_twice(self, monkeypatch, taps):
        # Two taps would pause and then immediately resume.
        playing(monkeypatch, True)
        guard = MediaGuard()
        guard.pause_if_playing()
        guard.pause_if_playing()
        assert taps == ["tap"]

    def test_when_detection_is_unavailable_it_does_nothing(self, monkeypatch, taps):
        playing(monkeypatch, Unavailable("no Core Audio"))
        guard = MediaGuard()
        assert not guard.pause_if_playing()
        assert taps == []
        assert not guard.paused_by_us

    def test_it_complains_about_that_only_once(self, monkeypatch, caplog):
        playing(monkeypatch, Unavailable("no Core Audio"))
        guard = MediaGuard()
        with caplog.at_level("INFO", logger="mlqvoice.media"):
            for _ in range(5):
                guard.pause_if_playing()
        assert sum("مکثِ خودکارِ پخش" in r.message for r in caplog.records) == 1

    def test_a_failed_key_does_not_leave_it_thinking_it_paused(self, monkeypatch):
        # Otherwise the next stop would send a stray tap and start the music.
        playing(monkeypatch, True)
        monkeypatch.setattr(media, "send_play_pause", _boom)
        guard = MediaGuard()
        assert not guard.pause_if_playing()
        assert not guard.paused_by_us

    def test_the_ignore_list_is_asked_each_time(self, monkeypatch, taps):
        # The browser is launched after the guard exists and is restarted with a
        # new pid, so a set captured at construction would go stale.
        seen = []
        monkeypatch.setattr(media, "is_audio_playing", lambda ignore: seen.append(ignore) or False)
        pids = {1}
        guard = MediaGuard(ignore_pids=lambda: set(pids))
        guard.pause_if_playing()
        pids.add(2)
        guard.pause_if_playing()
        assert seen == [{1}, {1, 2}]


class TestResume:
    def test_resumes_what_it_paused(self, monkeypatch, taps):
        playing(monkeypatch, True)
        guard = MediaGuard()
        guard.pause_if_playing()
        assert guard.resume_if_paused()
        assert taps == ["tap", "tap"]
        assert not guard.paused_by_us

    def test_never_resumes_what_it_did_not_pause(self, monkeypatch, taps):
        # The nastiest failure this feature could have: music starts by itself
        # because the box was opened while everything was already quiet.
        playing(monkeypatch, False)
        guard = MediaGuard()
        guard.pause_if_playing()
        assert not guard.resume_if_paused()
        assert taps == []

    def test_a_bare_resume_does_nothing(self, taps):
        assert not MediaGuard().resume_if_paused()
        assert taps == []

    def test_resuming_twice_only_sends_one_key(self, monkeypatch, taps):
        playing(monkeypatch, True)
        guard = MediaGuard()
        guard.pause_if_playing()
        guard.resume_if_paused()
        guard.resume_if_paused()
        assert taps == ["tap", "tap"]

    def test_forget_drops_the_memory_without_sending_anything(self, monkeypatch, taps):
        playing(monkeypatch, True)
        guard = MediaGuard()
        guard.pause_if_playing()
        guard.forget()
        assert not guard.resume_if_paused()
        assert taps == ["tap"]

    def test_a_failed_key_is_not_retried_later(self, monkeypatch):
        # A retry would arrive after the user pressed play themselves, and would
        # pause the music instead of resuming it.
        playing(monkeypatch, True)
        guard = MediaGuard()
        guard.pause_if_playing()
        monkeypatch.setattr(media, "send_play_pause", _boom)
        assert not guard.resume_if_paused()
        assert not guard.paused_by_us


class TestTheKeyItself:
    def test_it_is_a_press_and_a_release(self, monkeypatch):
        batches = []
        monkeypatch.setattr(media, "send_input", batches.append)
        media.send_play_pause()
        (batch,) = batches
        assert [i.ki.wVk for i in batch] == [0xB3, 0xB3]
        assert [i.ki.dwFlags for i in batch] == [0, KEYEVENTF_KEYUP]

    def test_both_events_go_out_in_one_call(self, monkeypatch):
        # Split across two calls, a physical keypress could land between them.
        calls = []
        monkeypatch.setattr(media, "send_input", lambda batch: calls.append(len(batch)))
        media.send_play_pause()
        assert calls == [2]


class TestProcessTree:
    def test_our_own_pid_is_always_included(self):
        import os

        assert os.getpid() in media.process_tree(os.getpid())

    def test_a_dead_pid_does_not_raise(self):
        # Chrome may exit while we are walking its children.
        assert media.process_tree(2**30) == {2**30}


def _boom():
    raise RuntimeError("SendInput رد کرد")
