"""Overlay behaviour, driven headless.

These exercise the widget itself rather than the functions behind it: the box the
user edits is where a wrong decision (interim text overwriting an edit, the
insert button firing on an empty box) actually shows up.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 نصب نیست")

from PySide6.QtWidgets import QApplication

from mlqvoice.ui.overlay import Overlay
from mlqvoice.ui.tray import make_icon


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def overlay(qt_app):
    w = Overlay()
    yield w
    w.close()
    w.deleteLater()


class TestText:
    def test_starts_empty(self, overlay):
        assert overlay.text() == ""

    def test_append_final_accumulates_with_a_space(self, overlay):
        overlay.append_final("سلام")
        overlay.append_final("دنیا")
        assert overlay.text() == "سلام دنیا"

    def test_append_final_ignores_blank_chunks(self, overlay):
        overlay.append_final("سلام")
        overlay.append_final("   ")
        assert overlay.text() == "سلام"

    def test_a_newline_inside_one_chunk_is_kept(self, overlay):
        # "خط جدید" becomes a real newline in the pipeline, inside a single chunk.
        overlay.append_final("اول\nدوم")
        assert overlay.text() == "اول\nدوم"

    def test_no_space_is_added_after_a_line_the_user_ended(self, overlay):
        overlay._text.setPlainText("اول\n")
        overlay.append_final("دوم")
        assert overlay.text() == "اول\nدوم"

    def test_interim_never_touches_the_editable_text(self, overlay):
        # Web Speech rewrites interim text constantly; if it landed in the box it
        # would fight the user for the cursor.
        overlay.append_final("سلام")
        overlay.set_interim("دنیا")
        assert overlay.text() == "سلام"

    def test_a_final_chunk_clears_the_interim_line(self, overlay):
        overlay.set_interim("در حالِ گفتن")
        overlay.append_final("گفتم")
        assert overlay._interim.text() == ""

    def test_clear_empties_both(self, overlay):
        overlay.append_final("سلام")
        overlay.set_interim("دنیا")
        overlay.clear()
        assert overlay.text() == ""
        assert overlay._interim.text() == ""

    def test_user_edits_survive_a_new_chunk(self, overlay):
        overlay.append_final("سلام")
        overlay._text.setPlainText("دست‌کاری‌شده")
        overlay.append_final("بعدی")
        assert overlay.text() == "دست‌کاری‌شده بعدی"


class TestInsertButton:
    def test_disabled_while_empty(self, overlay):
        assert not overlay._insert.isEnabled()

    def test_enabled_once_there_is_text(self, overlay):
        overlay.append_final("سلام")
        assert overlay._insert.isEnabled()

    def test_disabled_again_after_clearing(self, overlay):
        overlay.append_final("سلام")
        overlay.clear()
        assert not overlay._insert.isEnabled()

    def test_whitespace_only_does_not_enable_it(self, overlay):
        overlay._text.setPlainText("   \n  ")
        assert not overlay._insert.isEnabled()

    def test_emits_the_trimmed_text(self, overlay):
        got = []
        overlay.insertRequested.connect(got.append)
        overlay._text.setPlainText("  سلام دنیا  ")
        overlay._emit_insert()
        assert got == ["سلام دنیا"]

    def test_does_not_emit_when_empty(self, overlay):
        got = []
        overlay.insertRequested.connect(got.append)
        overlay._emit_insert()
        assert got == []


class TestState:
    def test_recording_label(self, overlay):
        overlay.set_recording(True)
        assert "ضبط" in overlay._state.text()
        assert overlay._toggle.text() == "توقف"

    def test_stopped_label_offers_to_resume(self, overlay):
        overlay.set_recording(False)
        assert overlay._toggle.text() == "ادامه"

    def test_stopping_drops_the_interim_guess(self, overlay):
        overlay.set_interim("نیمه‌کاره")
        overlay.set_recording(False)
        assert overlay._interim.text() == ""

    def test_target_title_is_shown(self, overlay):
        overlay.set_target("VS Code")
        assert "VS Code" in overlay._target.text()

    def test_missing_target_says_so_rather_than_showing_nothing(self, overlay):
        overlay.set_target("")
        assert overlay._target.text().strip() != ""


class TestWindow:
    def test_is_right_to_left(self, overlay):
        from PySide6.QtCore import Qt

        assert overlay.layoutDirection() == Qt.LayoutDirection.RightToLeft

    def test_stays_on_top_and_is_frameless(self, overlay):
        from PySide6.QtCore import Qt

        flags = overlay.windowFlags()
        assert flags & Qt.WindowType.WindowStaysOnTopHint
        assert flags & Qt.WindowType.FramelessWindowHint

    def test_dismiss_hides_and_signals(self, overlay):
        overlay.present()
        seen = []
        overlay.dismissed.connect(lambda: seen.append(True))
        overlay.dismiss()
        assert not overlay.isVisible()
        assert seen == [True]


class TestTrayIcon:
    def test_icon_renders_in_both_states(self, qt_app):
        assert not make_icon(False).isNull()
        assert not make_icon(True).isNull()
