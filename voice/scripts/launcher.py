"""Entry point for PyInstaller.

Two problems are solved here, both of which only exist in the *built* exe:

1. PyInstaller is handed a *script*, and a script has no parent package — so
   aiming it straight at ``src/mlqvoice/__main__.py`` makes every relative
   import in the package fail with "attempted relative import with no known
   parent package", and the exe dies before drawing anything.  Importing the
   package by name from outside it gives those imports a package to be
   relative to.

2. A ``--windowed`` build has no console, and PyInstaller sets ``sys.stdout``
   and ``sys.stderr`` to ``None``.  The first ``print`` anywhere — a CLI
   subcommand, a logging handler, a traceback — then raises
   ``AttributeError: 'NoneType' object has no attribute 'write'``.  So: attach
   to the parent console when the user launched us from a terminal, and fall
   back to a sink when there is genuinely nowhere to write.

   Attaching is not enough on its own.  A borrowed console still has whatever
   code page Windows gave it — 437 on an English install — and the streams
   below write UTF-8.  Persian then arrives as mojibake: output that exists and
   is useless, which reads as a *different* bug and sends you looking in the
   wrong place.  ``install.ps1`` learned this the hard way and sets the same
   thing; the exe had never been told.
"""

from __future__ import annotations

import os
import sys

ATTACH_PARENT_PROCESS = -1
CP_UTF8 = 65001


def attach_parent_console() -> bool:
    """Reuse the terminal we were launched from, if there is one."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        if not ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            return False
        # Best effort: a console that refuses UTF-8 is still better than none,
        # and Latin text stays readable either way.
        ctypes.windll.kernel32.SetConsoleOutputCP(CP_UTF8)
        return True
    except (OSError, AttributeError):
        return False


def ensure_streams() -> None:
    """Guarantee ``sys.stdout``/``sys.stderr`` are writable objects.

    The console is only touched when a stream is actually missing.  When the
    caller redirected our output to a file or a pipe the streams are already
    fine, and attaching a console on top of that buys nothing while adding a
    way for the process to behave unexpectedly.
    """
    missing = [n for n in ("stdout", "stderr") if getattr(sys, n, None) is None]
    if not missing:
        return

    attached = attach_parent_console()
    for name in missing:
        if attached:
            try:
                setattr(sys, name, open("CONOUT$", "w", encoding="utf-8", buffering=1))  # noqa: SIM115
                continue
            except OSError:
                pass
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def main() -> int:
    ensure_streams()
    from mlqvoice.__main__ import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
