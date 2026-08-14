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
"""

from __future__ import annotations

import os
import sys

ATTACH_PARENT_PROCESS = -1


def attach_parent_console() -> bool:
    """Reuse the terminal we were launched from, if there is one."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS))
    except (OSError, AttributeError):
        return False


def ensure_streams() -> None:
    """Guarantee ``sys.stdout``/``sys.stderr`` are writable objects."""
    attached = attach_parent_console()
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None:
            continue
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
