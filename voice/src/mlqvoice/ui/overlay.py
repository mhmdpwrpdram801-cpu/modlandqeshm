"""The box that appears in the middle of the screen.

One decision here is worth stating up front: recognised text lands in the
editable box only when it is *final*.  Interim guesses go to a separate line
underneath.  Web Speech revises its interim text constantly, so writing it into
the box would fight the user for the cursor and quietly undo their edits — and
editing is the whole point of showing a box at all.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_QSS = """
#card {
    background: #191c22;
    border: 1px solid #2c313c;
    border-radius: 14px;
}
#title { color: #e7ecf5; font-size: 14px; font-weight: 600; }
#target { color: #7d879b; font-size: 11px; }
#state { font-size: 12px; }
#interim { color: #7d879b; font-size: 12px; font-style: italic; }
QTextEdit {
    background: #11141a; color: #e7ecf5;
    border: 1px solid #2c313c; border-radius: 10px;
    padding: 10px; font-size: 15px;
    selection-background-color: #2f6df6;
}
QPushButton {
    background: #232833; color: #e7ecf5; border: 1px solid #333a48;
    border-radius: 9px; padding: 8px 14px; font-size: 13px;
}
QPushButton:hover { background: #2b3140; }
QPushButton:disabled { color: #5b6377; background: #1c2028; }
QPushButton#primary { background: #2f6df6; border-color: #2f6df6; color: #fff; }
QPushButton#primary:hover { background: #4880ff; }
QPushButton#primary:disabled { background: #23304d; border-color: #23304d; color: #8b9ab8; }
"""


class Overlay(QWidget):
    """Frameless, always-on-top, centred, right-to-left."""

    insertRequested = Signal(str)
    copyRequested = Signal(str)
    toggleRequested = Signal()
    dismissed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("mlqvoice")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(_QSS)
        self.resize(560, 340)

        self._drag_from = None
        self._build()
        self._shortcuts()

    # -- construction ----------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget(objectName="card")
        outer.addWidget(card)
        root = QVBoxLayout(card)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self._title = QLabel("گفتار به متن", objectName="title")
        self._target = QLabel("", objectName="target")
        titles.addWidget(self._title)
        titles.addWidget(self._target)
        header.addLayout(titles)
        header.addStretch(1)
        self._state = QLabel("", objectName="state")
        header.addWidget(self._state)
        root.addLayout(header)

        self._text = QTextEdit()
        self._text.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._text.setAcceptRichText(False)
        self._text.setPlaceholderText("حرف بزن…")
        font = QFont("Vazirmatn")
        font.setStyleHint(QFont.StyleHint.SansSerif)
        font.setPointSize(11)
        self._text.setFont(font)
        root.addWidget(self._text, 1)

        self._interim = QLabel("", objectName="interim")
        self._interim.setWordWrap(True)
        root.addWidget(self._interim)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._insert = QPushButton("بنویس", objectName="primary")
        self._insert.setToolTip("متن را در همان پنجره‌ای بنویس که قبلش توش بودی (Ctrl+Enter)")
        self._insert.clicked.connect(self._emit_insert)
        buttons.addWidget(self._insert)

        self._toggle = QPushButton("توقف")
        self._toggle.setToolTip("شروع/توقفِ ضبط — همان کاری که کلیدِ میان‌بُر می‌کند")
        self._toggle.clicked.connect(self.toggleRequested)
        buttons.addWidget(self._toggle)

        copy = QPushButton("کپی")
        copy.clicked.connect(lambda: self.copyRequested.emit(self.text()))
        buttons.addWidget(copy)

        clear = QPushButton("پاک کن")
        clear.clicked.connect(self.clear)
        buttons.addWidget(clear)

        buttons.addStretch(1)
        close = QPushButton("بستن")
        close.clicked.connect(self.dismiss)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._text.textChanged.connect(self._sync_insert_enabled)
        self._sync_insert_enabled()

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Return"), self, self._emit_insert)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self._emit_insert)
        QShortcut(QKeySequence("Esc"), self, self.dismiss)

    # -- state -----------------------------------------------------------

    def text(self) -> str:
        return self._text.toPlainText().strip()

    def clear(self) -> None:
        self._text.clear()
        self._interim.clear()

    def append_final(self, chunk: str) -> None:
        """Add a finished phrase, keeping the user's cursor and edits intact."""
        chunk = chunk.strip()
        if not chunk:
            return
        current = self._text.toPlainText()
        joiner = "" if not current or current.endswith(("\n", " ")) else " "
        cursor = self._text.textCursor()
        at_end = cursor.atEnd()
        self._text.moveCursor(cursor.MoveOperation.End)
        self._text.insertPlainText(joiner + chunk)
        if not at_end:
            self._text.setTextCursor(cursor)
        self._interim.clear()

    def set_interim(self, text: str) -> None:
        self._interim.setText(text.strip())

    def set_recording(self, recording: bool) -> None:
        if recording:
            self._state.setText("● در حالِ ضبط")
            self._state.setStyleSheet("color:#ff6b6b;")
            self._toggle.setText("توقف")
        else:
            self._state.setText("■ متوقف")
            self._state.setStyleSheet("color:#7d879b;")
            self._toggle.setText("ادامه")
            self._interim.clear()

    def set_status(self, message: str, *, bad: bool = False) -> None:
        self._state.setText(message)
        self._state.setStyleSheet("color:#ff6b6b;" if bad else "color:#7d879b;")

    def set_target(self, title: str) -> None:
        self._target.setText(f"مقصد: {title}" if title else "مقصدی شناسایی نشد")
        self._sync_insert_enabled()

    def _sync_insert_enabled(self) -> None:
        self._insert.setEnabled(bool(self._text.toPlainText().strip()))

    def _emit_insert(self) -> None:
        text = self.text()
        if text:
            self.insertRequested.emit(text)

    # -- window behaviour ------------------------------------------------

    def center_on_cursor_screen(self) -> None:
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center())
        cursor_screen = QApplication.screenAt(self.cursor().pos())
        geo = (cursor_screen or screen or QGuiApplication.primaryScreen()).availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(geo.center())
        self.move(frame.topLeft())

    def present(self) -> None:
        self.center_on_cursor_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        self._text.setFocus()

    def dismiss(self) -> None:
        self.hide()
        self.dismissed.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_from = None
        event.accept()
