"""The typeface, loaded from the app's own files.

The first version just asked Qt for ``QFont("Vazirmatn")``.  On a machine that
does not have Vazirmatn installed — which is nearly every Windows machine — Qt
silently falls back to whatever it considers default, and for Persian that
fallback is usually a face with no proper Arabic shaping.  Nothing errors; the
text simply looks wrong.  So the font ships *with* the app and is registered at
startup, and the fallback chain below is only ever reached if that registration
somehow fails.
"""

from __future__ import annotations

import logging
from importlib.resources import files
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

log = logging.getLogger(__name__)

FAMILY = "Vazirmatn"

#: Faces that actually ship with Windows and render Persian acceptably, in
#: descending order of how well they do it. Only used if the bundled font fails.
FALLBACKS = ("Segoe UI", "Tahoma", "Arial")

_BUNDLED = (
    "Vazirmatn-Regular.ttf",
    "Vazirmatn-Medium.ttf",
    "Vazirmatn-SemiBold.ttf",
)

_loaded: list[str] = []


def font_dir() -> Path:
    return Path(str(files("mlqvoice") / "assets" / "fonts"))


def load_fonts() -> list[str]:
    """Register the bundled faces with Qt. Safe to call more than once."""
    global _loaded
    if _loaded:
        return _loaded

    families: list[str] = []
    directory = font_dir()
    for name in _BUNDLED:
        path = directory / name
        if not path.exists():
            log.warning("فونتِ همراه پیدا نشد: %s", path)
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            log.warning("فونت بار نشد: %s", path)
            continue
        families.extend(QFontDatabase.applicationFontFamilies(font_id))

    _loaded = sorted(set(families))
    if not _loaded:
        log.warning("هیچ فونتِ همراهی بار نشد؛ به فونت‌های خودِ ویندوز برمی‌گردیم")
    return _loaded


def available() -> bool:
    """Whether the bundled family is registered and usable."""
    return FAMILY in _loaded or FAMILY in QFontDatabase.families()


def ui_font(size: int = 11, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """A font for interface text, with the fallback chain already attached."""
    font = QFont()
    font.setFamilies([FAMILY, *FALLBACKS])
    font.setPointSize(size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def css_stack() -> str:
    """The same chain, for use inside a Qt style sheet."""
    return ", ".join(f'"{name}"' for name in (FAMILY, *FALLBACKS))
