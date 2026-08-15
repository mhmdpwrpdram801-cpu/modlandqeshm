"""The box that appears in the middle of the screen.

Two decisions here are worth stating up front.

Recognised text lands in the editable box only when it is *final*.  Interim
guesses go to a separate line underneath.  Web Speech revises its interim text
constantly, so writing it into the box would fight the user for the cursor and
quietly undo their edits — and editing is the whole point of showing a box.

And the box is emptied when a session *begins*, not when it ends.  Clearing on
close would throw the text away the instant somebody hits Esc by accident;
clearing on open still guarantees what the user actually asked for, which is
that yesterday's dictation is never sitting there waiting for them.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .fonts import css_stack, load_fonts, ui_font

# Colours live here rather than being sprinkled through the code, so the whole
# palette can be judged — and changed — in one place.
INK = "#eef2fa"
INK_DIM = "#8892a6"
EDGE = "#2a3040"
REC = "#ff5f6d"
ACCENT = "#5b8cff"


def _qss() -> str:
    return f"""
#card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1c2029, stop:1 #14171e);
    border: 1px solid {EDGE};
    border-radius: 18px;
}}
#title  {{ color: {INK};     font-size: 15px; font-weight: 600; }}
#target {{ color: {INK_DIM}; font-size: 11px; }}
#state  {{ font-size: 12px; font-weight: 500; }}
#interim {{ color: {INK_DIM}; font-size: 12px; font-style: italic; }}
#hint   {{ color: #5d6678;   font-size: 11px; }}

QTextEdit {{
    background: #0f1218;
    color: {INK};
    border: 1px solid {EDGE};
    border-radius: 12px;
    padding: 12px 14px;
    font-size: 16px;
    line-height: 170%;
    selection-background-color: {ACCENT};
    selection-color: #fff;
}}
QTextEdit:focus {{ border: 1px solid #3d4759; }}

QPushButton {{
    background: #232936;
    color: {INK};
    border: 1px solid #333c4d;
    border-radius: 10px;
    padding: 9px 16px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover  {{ background: #2c3444; border-color: #3f4a5e; }}
QPushButton:pressed {{ background: #202634; }}
QPushButton:disabled {{ color: #4d5568; background: #1a1e27; border-color: #262c38; }}

QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #6d99ff, stop:1 {ACCENT});
    border: 1px solid #6d99ff;
    color: #fff;
    font-weight: 600;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #7ea6ff, stop:1 #6d99ff);
}}
QPushButton#primary:disabled {{
    background: #212a3d; border-color: #212a3d; color: #6b7794;
}}
QPushButton#ghost {{ background: transparent; border-color: #2c3444; color: {INK_DIM}; }}
QPushButton#ghost:hover {{ background: #1f2530; color: {INK}; }}

* {{ font-family: {css_stack()}; }}
"""


class Overlay(QWidget):
    """Frameless, always-on-top, centred, right-to-left."""

    insertRequested = Signal(str)
    copyRequested = Signal(str)
    finglishRequested = Signal(str)
    toggleRequested = Signal()
    dismissed = Signal()

    def __init__(self) -> None:
        super().__init__()
        load_fonts()
        self.setWindowTitle("mlqvoice")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setFont(ui_font(11))
        self.setStyleSheet(_qss())
        self.resize(600, 380)

        self._drag_from = None
        self._pulse_on = False
        self._pulse = QTimer(self)
        self._pulse.setInterval(600)
        self._pulse.timeout.connect(self._tick_pulse)
        self._fade: QPropertyAnimation | None = None

        self._build()
        self._shortcuts()

    # -- construction ----------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        # Room for the drop shadow to fall into; without it the shadow is clipped.
        outer.setContentsMargins(18, 18, 18, 18)

        card = QWidget(objectName="card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(42)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 190))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(3)
        self._title = QLabel("گفتار به متن", objectName="title")
        self._title.setFont(ui_font(12, QFont.Weight.DemiBold))
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
        self._text.setFont(ui_font(13))
        # Widget direction alone leaves an *empty* paragraph laid out left-to-right,
        # so the caret sat on the wrong side until the first character arrived.
        # The document needs its own base direction.
        # Widget direction alone leaves an *empty* paragraph laid out left to
        # right, so the caret sat on the wrong side until the first character
        # arrived. The document needs its own base direction.
        #
        # Measured, because the obvious extra step makes it worse: adding
        # setAlignment(AlignRight) on top puts the caret back on the LEFT — Qt
        # mirrors alignment flags inside a right-to-left widget, so "right"
        # becomes the trailing edge. Direction alone is both necessary and
        # sufficient, and it survives clear().
        option = self._text.document().defaultTextOption()
        option.setTextDirection(Qt.LayoutDirection.RightToLeft)
        self._text.document().setDefaultTextOption(option)
        root.addWidget(self._text, 1)

        # The interim guess and the keyboard hint share one row. The hint used to
        # sit between two buttons, where it read as clutter; here it costs no
        # extra height because this row is reserved anyway.
        underline = QHBoxLayout()
        underline.setSpacing(12)
        self._interim = QLabel("", objectName="interim")
        self._interim.setWordWrap(True)
        self._interim.setMinimumHeight(18)
        underline.addWidget(self._interim, 1)
        self._hint = QLabel("Ctrl+Enter بنویس · Ctrl+L فارسی · Esc ببند", objectName="hint")
        underline.addWidget(self._hint, 0)
        root.addLayout(underline)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        self._insert = QPushButton("بنویس", objectName="primary")
        self._insert.setToolTip("متن را در همان پنجره‌ای بنویس که قبلش توش بودی (Ctrl+Enter)")
        self._insert.clicked.connect(self._emit_insert)
        buttons.addWidget(self._insert)

        self._toggle = QPushButton("توقف")
        self._toggle.setToolTip("شروع/توقفِ ضبط — همان کاری که کلیدِ میان‌بُر می‌کند")
        self._toggle.clicked.connect(self.toggleRequested)
        buttons.addWidget(self._toggle)

        self._finglish = QPushButton("فارسی‌ش کن")
        self._finglish.setToolTip(
            "حروفِ لاتینِ فینگلیش را فارسی کن (Ctrl+L) — کد و واژه‌های فنی دست نمی‌خورند"
        )
        self._finglish.clicked.connect(lambda: self.finglishRequested.emit(self.text()))
        buttons.addWidget(self._finglish)

        copy = QPushButton("کپی")
        copy.clicked.connect(lambda: self.copyRequested.emit(self.text()))
        buttons.addWidget(copy)

        clear = QPushButton("پاک کن", objectName="ghost")
        clear.clicked.connect(self.clear)
        buttons.addWidget(clear)

        buttons.addStretch(1)
        close = QPushButton("بستن", objectName="ghost")
        close.clicked.connect(self.dismiss)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._text.textChanged.connect(self._sync_insert_enabled)
        self._sync_insert_enabled()

    def _shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+Return"), self, self._emit_insert)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self._emit_insert)
        QShortcut(QKeySequence("Esc"), self, self.dismiss)
        QShortcut(QKeySequence("Ctrl+L"), self, lambda: self.finglishRequested.emit(self.text()))

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

    def set_text(self, text: str) -> None:
        """Replace the whole box — used by conversions that rewrite in place."""
        self._text.setPlainText(text)
        self._text.moveCursor(self._text.textCursor().MoveOperation.End)

    def set_interim(self, text: str) -> None:
        self._interim.setText(text.strip())

    def set_recording(self, recording: bool) -> None:
        if recording:
            self._pulse_on = True
            self._render_state()
            self._pulse.start()
            self._toggle.setText("توقف")
        else:
            self._pulse.stop()
            self._state.setText("■ متوقف")
            self._state.setStyleSheet(f"color:{INK_DIM};")
            self._toggle.setText("ادامه")
            self._interim.clear()

    def _tick_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        self._render_state()

    def _render_state(self) -> None:
        dot = "●" if self._pulse_on else "○"
        self._state.setText(f"{dot} در حالِ ضبط")
        self._state.setStyleSheet(f"color:{REC};")

    def set_status(self, message: str, *, bad: bool = False) -> None:
        self._pulse.stop()
        self._state.setText(message)
        self._state.setStyleSheet(f"color:{REC};" if bad else f"color:{INK_DIM};")

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
        cursor_screen = QApplication.screenAt(self.cursor().pos())
        geo = (cursor_screen or QGuiApplication.primaryScreen()).availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(geo.center())
        self.move(frame.topLeft())

    def begin_session(self, target_title: str = "") -> None:
        """Open the box for a fresh dictation.

        This is the fix for text from a previous dictation still sitting in the
        box: ``present`` alone never emptied it, and the only ``clear`` was on
        the successful-insert path — so closing with Esc kept the text forever.
        """
        self.clear()
        self.set_target(target_title)
        self.present()

    def present(self) -> None:
        """Show the box without touching its contents."""
        self.center_on_cursor_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        self._text.setFocus()
        self._fade_in()

    def _fade_in(self) -> None:
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(130)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()

    def dismiss(self) -> None:
        self._pulse.stop()
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
