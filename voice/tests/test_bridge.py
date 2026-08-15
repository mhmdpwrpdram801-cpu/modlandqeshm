import json
import threading
import urllib.error
import urllib.request

import pytest

from mlqvoice.bridge import BrowserNotFound, RecognizerBridge, Result, find_browser


@pytest.fixture
def bridge():
    results: list[Result] = []
    statuses: list[tuple[str, str]] = []
    b = RecognizerBridge(
        on_result=results.append,
        on_status=lambda s, d: statuses.append((s, d)),
    )
    b.start()
    b.results, b.statuses = results, statuses
    try:
        yield b
    finally:
        b.stop()


def get(bridge, path, token=None, timeout=5):
    token = bridge.token if token is None else token
    url = f"http://127.0.0.1:{bridge.port}{path}?t={token}"
    return urllib.request.urlopen(url, timeout=timeout)


def post(bridge, path, payload, token=None, timeout=5):
    token = bridge.token if token is None else token
    req = urllib.request.Request(
        f"http://127.0.0.1:{bridge.port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Token": token},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout)


class TestAuth:
    def test_page_is_served_with_the_token(self, bridge):
        body = get(bridge, "/").read().decode()
        assert "webkitSpeechRecognition" in body
        assert bridge.token in body

    def test_the_placeholder_is_actually_substituted(self, bridge):
        assert "__TOKEN__" not in get(bridge, "/").read().decode()

    def test_page_is_refused_without_the_token(self, bridge):
        with pytest.raises(urllib.error.HTTPError) as exc:
            get(bridge, "/", token="wrong")
        assert exc.value.code == 403

    def test_result_is_refused_without_the_token(self, bridge):
        # This is the one that matters: /result types into the user's keyboard,
        # so any local process must not be able to reach it.
        with pytest.raises(urllib.error.HTTPError) as exc:
            post(bridge, "/result", {"text": "نفوذی", "final": True}, token="wrong")
        assert exc.value.code == 403
        assert bridge.results == []

    def test_tokens_differ_between_instances(self):
        assert RecognizerBridge().token != RecognizerBridge().token

    def test_unknown_path(self, bridge):
        with pytest.raises(urllib.error.HTTPError) as exc:
            get(bridge, "/secrets")
        assert exc.value.code == 404


class TestResults:
    def test_final_result_arrives(self, bridge):
        post(bridge, "/result", {"text": "سلام", "final": True})
        assert bridge.results == [Result(text="سلام", final=True)]

    def test_interim_result_is_flagged(self, bridge):
        post(bridge, "/result", {"text": "سلا", "final": False})
        assert bridge.results[0].final is False

    def test_missing_text_is_dropped_not_crashed_on(self, bridge):
        post(bridge, "/result", {"final": True})
        assert bridge.results == []

    def test_non_string_text_is_dropped(self, bridge):
        post(bridge, "/result", {"text": 42, "final": True})
        assert bridge.results == []

    def test_broken_json_gets_400(self, bridge):
        req = urllib.request.Request(
            f"http://127.0.0.1:{bridge.port}/result",
            data=b"{ not json",
            headers={"X-Token": bridge.token},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 400

    def test_oversized_body_is_rejected(self, bridge):
        req = urllib.request.Request(
            f"http://127.0.0.1:{bridge.port}/result",
            data=b'{"text":"' + b"x" * (64 * 1024) + b'"}',
            headers={"X-Token": bridge.token},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 400

    def test_status_arrives(self, bridge):
        post(bridge, "/status", {"state": "listening", "detail": ""})
        assert bridge.statuses == [("listening", "")]


class TestEvents:
    def test_start_command_reaches_a_subscriber(self, bridge):
        received = []
        ready = threading.Event()

        def reader():
            stream = get(bridge, "/events", timeout=10)
            ready.set()
            for raw in stream:
                line = raw.decode().strip()
                if line.startswith("data:"):
                    received.append(json.loads(line[5:]))
                    return

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        assert ready.wait(5)
        # Wait for the handler to actually register before broadcasting.
        for _ in range(100):
            if bridge.client_count:
                break
            threading.Event().wait(0.02)
        bridge.start_recording()
        t.join(timeout=5)
        assert received == [{"cmd": "start", "lang": "fa-IR", "interim": True}]

    def test_subscribers_are_dropped_on_stop(self, bridge):
        q = bridge.subscribe()
        assert bridge.client_count == 1
        bridge.unsubscribe(q)
        assert bridge.client_count == 0


class TestServer:
    def test_binds_loopback_only(self, bridge):
        assert bridge._server.server_address[0] == "127.0.0.1"

    def test_port_before_start_is_an_error_not_a_zero(self):
        with pytest.raises(RuntimeError):
            _ = RecognizerBridge().port

    def test_stop_is_idempotent(self, bridge):
        bridge.stop()
        bridge.stop()


class TestBrowserLookup:
    def test_configured_path_that_does_not_exist_is_reported(self, tmp_path):
        with pytest.raises(BrowserNotFound, match="تنظیم‌شده"):
            find_browser(str(tmp_path / "nope.exe"))

    def test_configured_path_that_exists_is_used(self, tmp_path):
        exe = tmp_path / "chrome.exe"
        exe.write_text("")
        assert find_browser(str(exe)) == str(exe)


class TestCommandsBeforeTheBrowserIsUp:
    """The reported bug: press the hotkey, nothing happens.

    Chrome takes seconds to cold-start and connect. Every command sent in that
    window used to be handed to an empty client list and simply vanish — the
    user pressed the key, the app looked alive, and nothing came of it.
    """

    def test_a_command_with_no_client_is_kept(self, bridge):
        bridge.start_recording()
        assert bridge.pending_command == {
            "cmd": "start",
            "lang": bridge.lang,
            "interim": bridge.interim,
        }

    def test_the_late_client_receives_it(self, bridge):
        bridge.start_recording()
        q = bridge.subscribe()
        assert q.get_nowait()["cmd"] == "start"

    def test_only_the_last_command_is_kept(self, bridge):
        # Pressing the key twice before the page connects must not leave a
        # "start" queued behind a "stop".
        bridge.start_recording()
        bridge.stop_recording()
        q = bridge.subscribe()
        assert q.get_nowait()["cmd"] == "stop"
        assert q.empty()

    def test_a_delivered_command_is_not_kept(self, bridge):
        # Otherwise every reconnection would replay the last thing that was
        # already acted on.
        listening = bridge.subscribe()
        bridge.start_recording()
        assert listening.get_nowait()["cmd"] == "start"
        assert bridge.pending_command is None

    def test_a_second_client_does_not_get_a_replay(self, bridge):
        listening = bridge.subscribe()
        bridge.start_recording()
        listening.get_nowait()
        assert bridge.subscribe().empty()

    def test_a_stale_command_is_not_replayed(self, monkeypatch, bridge):
        # A page that reconnects minutes later must not suddenly start
        # recording on its own.
        #
        # The clock has to be fake *before* the command is sent — the first
        # version of this test patched it afterwards, so the command carried a
        # real timestamp, the elapsed time came out hugely negative, and the
        # check passed while proving nothing.
        import mlqvoice.bridge as mod

        now = [1000.0]
        monkeypatch.setattr(mod, "time", type("C", (), {"monotonic": staticmethod(lambda: now[0])}))
        bridge.start_recording()
        assert bridge.pending_command is not None  # fresh

        now[0] += mod.PENDING_TTL + 1
        assert bridge.pending_command is None
        assert bridge.subscribe().empty()
