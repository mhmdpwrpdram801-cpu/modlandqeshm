"""System-tray icon and menu.

The app has no main window, so without this there is no way to reach it — no way
to see the hotkey, open the dictionary, or quit.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def make_icon(recording: bool = False) -> QIcon:
    """A microphone drawn at run time, so the build needs no image assets."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ff5252") if recording else QColor("#dfe5f0"))
    painter.drawRoundedRect(QRect(24, 10, 16, 28), 8, 8)
    pen = painter.pen()
    pen.setColor(QColor("#ff5252") if recording else QColor("#dfe5f0"))
    pen.setWidth(5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRect(16, 22, 32, 26), 180 * 16, 180 * 16)
    painter.drawLine(32, 46, 32, 54)
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(self, hotkey_label: str, parent=None) -> None:
        super().__init__(make_icon(), parent)
        self._menu = QMenu()
        self._hotkey_item = self._menu.addAction(f"کلیدِ میان‌بُر: {hotkey_label}")
        self._hotkey_item.setEnabled(False)
        self._menu.addSeparator()

        self.show_action = QAction("بازکردنِ کادر", self._menu)
        self.dictionary_action = QAction("دیکشنریِ من", self._menu)
        self.learned_action = QAction("آنچه یاد گرفته", self._menu)
        self.config_action = QAction("تنظیمات", self._menu)
        self.quit_action = QAction("خروج", self._menu)
        for action in (
            self.show_action,
            self.dictionary_action,
            self.learned_action,
            self.config_action,
        ):
            self._menu.addAction(action)
        self._menu.addSeparator()
        self._menu.addAction(self.quit_action)

        self.setContextMenu(self._menu)
        self.setToolTip(f"mlqvoice — {hotkey_label}")

    def set_recording(self, recording: bool) -> None:
        self.setIcon(make_icon(recording))
