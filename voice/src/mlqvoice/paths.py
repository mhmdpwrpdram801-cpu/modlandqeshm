"""Where the app keeps the things the user owns.

Config and the personal dictionary live next to the user's other roaming data on
Windows.  A non-Windows fallback exists so the pure-logic tests can run anywhere;
the app itself refuses to start off Windows (see :mod:`mlqvoice.app`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "mlqvoice"


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


def browser_profile_dir() -> Path:
    """A private Chrome profile, so we never touch the user's own one."""
    path = data_dir() / "browser-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path
