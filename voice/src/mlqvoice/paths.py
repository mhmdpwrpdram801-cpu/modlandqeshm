"""Where the app keeps the things the user owns.

Config and the personal dictionary live next to the user's other roaming data on
Windows.  A non-Windows fallback exists so the pure-logic tests can run anywhere;
the app itself refuses to start off Windows (see :mod:`mlqvoice.app`).
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path

APP_DIR_NAME = "mlqvoice"


def write_atomic(path: Path, text: str) -> None:
    """Write *text* to *path* so the file is either the old one or the new one.

    ``write_text`` truncates before it writes, which means an interruption —
    a crash, a full disk, the machine losing power — leaves a file shorter than
    it was. Two of the three files this app owns shrug that off and start
    empty. ``dictionary.json`` does not: a half file is invalid JSON, and
    invalid JSON there used to stop the app from starting at all.

    The temporary file is made in the same directory on purpose. ``os.replace``
    is only atomic within one filesystem, and ``%TEMP%`` is regularly on a
    different one from ``%APPDATA%``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            # Without this the rename can land before the bytes do, and a power
            # cut in between leaves a file that exists and is empty.
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def data_dir() -> Path:
    """The per-user directory, created on first use."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return data_dir() / "config.json"


def user_dictionary_file() -> Path:
    return data_dir() / "dictionary.json"


def learned_file() -> Path:
    """Suggestions grown from the user's own corrections. Never leaves the machine."""
    return data_dir() / "learned.json"


def stats_file() -> Path:
    """Usage counts, for judging the dictionary on evidence rather than feel.

    Numbers only — see :mod:`mlqvoice.text.stats` for what is deliberately not
    in it. Never leaves the machine.
    """
    return data_dir() / "stats.json"


def browser_profile_dir() -> Path:
    """A private Chrome profile, so we never touch the user's own one."""
    path = data_dir() / "browser-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path
