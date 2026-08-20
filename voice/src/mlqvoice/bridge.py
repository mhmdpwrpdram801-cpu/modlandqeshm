"""The recognition bridge.

Why a browser is involved at all: the Persian recogniser this tool is asked to
use is Google's — the same engine behind the microphone button in Google
Translate — and the only way to reach it without a paid Cloud key is the Web
Speech API, which lives in Chrome.  Electron builds cannot use it (the Google
API keys are not in them), so instead the app serves a one-page site to the
Chrome the user already has, in a private profile and a window kept out of the
way, and talks to it over loopback.

The wire protocol is deliberately small:

* ``GET  /``        the page
* ``GET  /events``  server-sent events: ``{"cmd": "start"|"stop"}``
* ``POST /result``  ``{"text": str, "final": bool}``
* ``POST /status``  ``{"state": str, "detail": str}``

Every request carries a token minted at startup.  Without it, any other program
on the machine could POST text to ``/result`` — and this app types whatever it
receives into the user's keyboard.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import secrets
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from .paths import browser_profile_dir

log = logging.getLogger(__name__)

MAX_BODY = 64 * 1024  # a spoken chunk is tiny; anything larger is not ours

#: Ceiling on how much of a body we will read purely to throw it away. Far
#: above any real request, and there so a caller claiming ``Content-Length:
#: 2000000000`` cannot make the thread sit there reading it.
DRAIN_LIMIT = 1024 * 1024

#: How long a command waits for a browser that has not connected yet. Long
#: enough to cover Chrome starting cold, short enough that a page reconnecting
#: minutes later does not suddenly start recording on its own.
PENDING_TTL = 30.0


@dataclass(frozen=True)
class Result:
    text: str
    final: bool


class BrowserNotFound(RuntimeError):
    """No Chrome-family browser to run the recogniser in."""


CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def find_browser(explicit: str = "") -> str:
    """Locate Chrome or Edge, preferring anything the user configured."""
    if explicit:
        if not Path(explicit).exists():
            raise BrowserNotFound(f"مرورگرِ تنظیم‌شده پیدا نشد: {explicit}")
        return explicit

    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        *CHROME_CANDIDATES,
        *([rf"{local}\Google\Chrome\Application\chrome.exe"] if local else []),
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    for name in ("chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    raise BrowserNotFound(
        "کروم یا اِج پیدا نشد. یکی‌شان را نصب کن، یا مسیرش را در browser_path بگذار."
    )


class _Handler(BaseHTTPRequestHandler):
    server_version = "mlqvoice"
    bridge: RecognizerBridge  # set by the server
    _body_done = False  # per-request; the body must never be read twice

    def log_message(self, fmt: str, *args) -> None:
        log.debug("bridge %s", fmt % args)

    # -- helpers ---------------------------------------------------------

    def _authorised(self) -> bool:
        token = self.headers.get("X-Token", "")
        if not token and "?" in self.path:
            from urllib.parse import parse_qs, urlparse

            token = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
        return secrets.compare_digest(token, self.bridge.token)

    def _drain_body(self) -> None:
        """Swallow the request body so the socket can close instead of reset.

        Hanging up while the body still sits unread in the receive buffer makes
        the OS send RST rather than FIN, and Windows throws away everything
        buffered on a connection it resets — including the reply we just wrote.
        The caller is then told the network broke, when what we actually sent it
        was a perfectly clear ``403``.
        """
        if self._body_done:
            return  # already consumed; reading again would block forever
        self._body_done = True
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return  # nothing trustworthy to read; reading blind would hang
        if length > 0:
            with contextlib.suppress(OSError):
                self.rfile.read(min(length, DRAIN_LIMIT))

    def _answer(self, code: int) -> None:
        """Reply with a status and no body, in a way that survives the hang-up.

        ``send_response`` alone writes no ``Content-Length``, so the reply is
        delimited by nothing but the close — the one event a reset destroys.
        Saying the body is empty makes the answer complete the moment it lands,
        whatever happens to the socket afterwards; draining the request keeps
        the close from becoming a reset in the first place. Either one alone
        would probably have done, and that is the point of having both: this
        cost a red Windows CI run on a change that never touched the bridge.
        """
        self._drain_body()
        self.send_response(code)
        # 204 is self-delimiting by definition and the RFC forbids the header
        # there; every other bodyless status needs it said out loud.
        if code != 204:
            self.send_header("Content-Length", "0")
        self.end_headers()

    def _reject(self) -> None:
        self._answer(403)

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0:
            return None
        if length > MAX_BODY:
            return None  # refused unread, but _answer still drains it
        self._body_done = True
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:
        self._body_done = False
        if not self._authorised():
            self._reject()
            return
        path = self._path()
        if path == "/":
            body = self.bridge.page_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/events":
            self._stream_events()
        else:
            self._answer(404)

    def do_POST(self) -> None:
        self._body_done = False
        if not self._authorised():
            self._reject()
            return
        path = self._path()
        data = self._read_json()
        if data is None:
            self._answer(400)
            return

        if path == "/result":
            text = data.get("text")
            if isinstance(text, str):
                self.bridge.on_result(Result(text=text, final=bool(data.get("final"))))
        elif path == "/status":
            self.bridge.on_status(str(data.get("state", "")), str(data.get("detail", "")))
        else:
            self._answer(404)
            return

        self._answer(204)

    def _stream_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q = self.bridge.subscribe()
        try:
            while True:
                try:
                    payload = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")  # keeps proxies and Chrome happy
                    self.wfile.flush()
                    continue
                if payload is None:
                    return
                self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the page went away; it will reconnect on its own
        finally:
            self.bridge.unsubscribe(q)


class RecognizerBridge:
    """Owns the loopback server, the page, and the browser process."""

    def __init__(
        self,
        *,
        lang: str = "fa-IR",
        interim: bool = True,
        port: int = 0,
        browser_path: str = "",
        on_result: Callable[[Result], None] | None = None,
        on_status: Callable[[str, str], None] | None = None,
    ) -> None:
        self.token = secrets.token_urlsafe(24)
        self.lang = lang
        self.interim = interim
        self._requested_port = port
        self._browser_path = browser_path
        self._on_result = on_result or (lambda _r: None)
        self._on_status = on_status or (lambda _s, _d: None)

        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._browser: subprocess.Popen | None = None
        self._clients: list[queue.Queue] = []
        # The last command, kept only for a client that has yet to arrive.
        self._pending: tuple[dict, float] | None = None
        self._lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("سرور هنوز بالا نیامده")
        return self._server.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def start(self) -> None:
        handler = type("_BoundHandler", (_Handler,), {"bridge": self})
        self._server = ThreadingHTTPServer(("127.0.0.1", self._requested_port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="mlqvoice-bridge", daemon=True
        )
        self._thread.start()
        log.info("bridge listening on %s", self.port)

    def stop(self) -> None:
        with self._lock:
            for q in self._clients:
                q.put(None)
            self._clients.clear()
        if self._browser is not None:
            self._browser.terminate()
            self._browser = None
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def launch_browser(self) -> None:
        """Start the recogniser page in its own Chrome window, out of the way."""
        exe = find_browser(self._browser_path)
        args = [
            exe,
            f"--app={self.url}",
            f"--user-data-dir={browser_profile_dir()}",
            # Grants the microphone to our own loopback page without a prompt the
            # user cannot see; the private profile keeps this off their browsing.
            "--use-fake-ui-for-media-stream",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--window-size=360,120",
            "--window-position=-2400,-2400",
        ]
        creation = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        self._browser = subprocess.Popen(args, creationflags=creation)
        log.info("recogniser browser started: %s", exe)

    def browser_alive(self) -> bool:
        return self._browser is not None and self._browser.poll() is None

    @property
    def browser_pid(self) -> int:
        """The recogniser browser's pid, or 0 when it is not running.

        Used to keep our own Chrome out of the "is something playing?" question.
        A dead process's pid is not reported: the number gets recycled, and
        handing back a stale one would ignore whoever inherited it.
        """
        if self._browser is None or self._browser.poll() is not None:
            return 0
        return self._browser.pid

    # -- events ----------------------------------------------------------

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._clients.append(q)
            # Hand over a command that arrived before the page was listening.
            # Chrome takes a few seconds to start and connect, and every hotkey
            # press in that window used to vanish into an empty client list —
            # the user pressed the key, nothing happened, and nothing said why.
            pending = self._pending
        if pending is not None:
            payload, sent_at = pending
            if time.monotonic() - sent_at <= PENDING_TTL:
                q.put(payload)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def _broadcast(self, payload: dict) -> None:
        with self._lock:
            clients = list(self._clients)
            # Only worth keeping when nobody heard it. Holding on to a command
            # that *was* delivered would replay it at the next reconnection.
            self._pending = None if clients else (payload, time.monotonic())
        for q in clients:
            q.put(payload)

    @property
    def pending_command(self) -> dict | None:
        """The command still waiting for a browser, if any."""
        with self._lock:
            if self._pending is None:
                return None
            payload, sent_at = self._pending
        return payload if time.monotonic() - sent_at <= PENDING_TTL else None

    def start_recording(self) -> None:
        self._broadcast({"cmd": "start", "lang": self.lang, "interim": self.interim})

    def stop_recording(self) -> None:
        self._broadcast({"cmd": "stop"})

    # -- inbound ---------------------------------------------------------

    def on_result(self, result: Result) -> None:
        self._on_result(result)

    def on_status(self, state: str, detail: str) -> None:
        self._on_status(state, detail)

    # -- page ------------------------------------------------------------

    def page_html(self) -> str:
        template = (files("mlqvoice") / "web" / "recognizer.html").read_text(encoding="utf-8")
        return template.replace("__TOKEN__", self.token)
