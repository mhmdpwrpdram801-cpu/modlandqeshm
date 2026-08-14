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


class TestSessionLifecycle:
    """The reported bug: yesterday's dictation was still in the box today."""

    def test_begin_session_starts_empty(self, overlay):
        overlay.append_final("متنِ دفعه‌ی قبل")
        overlay.begin_session("Notepad")
        assert overlay.text() == ""

    def test_begin_session_clears_the_interim_line_too(self, overlay):
        overlay.set_interim("حدسِ نیمه‌کاره")
        overlay.begin_session("Notepad")
        assert overlay._interim.text() == ""

    def test_begin_session_sets_the_target(self, overlay):
        overlay.begin_session("VS Code")
        assert "VS Code" in overlay._target.text()

    def test_begin_session_shows_the_box(self, overlay):
        overlay.begin_session("Notepad")
        assert overlay.isVisible()

    def test_closing_then_beginning_again_does_not_carry_text_over(self, overlay):
        overlay.begin_session("Notepad")
        overlay.append_final("سلام")
        overlay.dismiss()
        overlay.begin_session("Notepad")
        assert overlay.text() == ""

    def test_present_alone_keeps_the_text(self, overlay):
        # The retry-after-failed-insert path re-shows the box and must NOT lose
        # what the user already dictated.
        overlay.append_final("متنی که باید بماند")
        overlay.present()
        assert overlay.text() == "متنی که باید بماند"


class TestRecordingIndicator:
    def test_pulse_runs_while_recording(self, overlay):
        overlay.set_recording(True)
        assert overlay._pulse.isActive()

    def test_pulse_stops_when_recording_stops(self, overlay):
        overlay.set_recording(True)
        overlay.set_recording(False)
        assert not overlay._pulse.isActive()

    def test_pulse_alternates_the_dot_but_keeps_the_words(self, overlay):
        overlay.set_recording(True)
        first = overlay._state.text()
        overlay._tick_pulse()
        second = overlay._state.text()
        assert first != second
        assert "ضبط" in first and "ضبط" in second

    def test_a_status_message_stops_the_pulse(self, overlay):
        overlay.set_recording(True)
        overlay.set_status("خطایی رخ داد", bad=True)
        assert not overlay._pulse.isActive()
        assert "خطایی رخ داد" in overlay._state.text()

    def test_dismiss_stops_the_pulse(self, overlay):
        overlay.set_recording(True)
        overlay.dismiss()
        assert not overlay._pulse.isActive()


class TestFonts:
    """The first version asked Qt for a font that is not on any Windows box.

    Nothing errored — Qt just fell back to a face with no Persian shaping and the
    text looked wrong. So the font ships with the app, and these check it is
    actually there and actually registers.
    """

    def test_the_ttf_files_are_shipped(self):
        from mlqvoice.ui.fonts import font_dir

        directory = font_dir()
        names = {p.name for p in directory.glob("*.ttf")}
        assert {"Vazirmatn-Regular.ttf", "Vazirmatn-Medium.ttf"} <= names

    def test_the_licence_ships_with_them(self):
        # SIL OFL lets us redistribute only if the licence travels along.
        from mlqvoice.ui.fonts import font_dir

        licence = font_dir() / "OFL.txt"
        assert licence.exists()
        assert "SIL Open Font License" in licence.read_text(encoding="utf-8")

    def test_qt_actually_registers_the_family(self, qt_app):
        from mlqvoice.ui.fonts import FAMILY, available, load_fonts

        assert FAMILY in load_fonts()
        assert available()

    def test_ui_font_puts_the_bundled_family_first(self, qt_app):
        from mlqvoice.ui.fonts import FALLBACKS, FAMILY, ui_font

        families = ui_font(12).families()
        assert families[0] == FAMILY
        assert list(FALLBACKS) == families[1:]

    def test_overlay_uses_it(self, overlay):
        from mlqvoice.ui.fonts import FAMILY

        assert FAMILY in overlay._text.font().families()

    def test_style_sheet_names_the_family(self, overlay):
        from mlqvoice.ui.fonts import FAMILY

        assert FAMILY in overlay.styleSheet()

    def test_the_document_itself_is_right_to_left(self, overlay):
        from PySide6.QtCore import Qt

        option = overlay._text.document().defaultTextOption()
        assert option.textDirection() == Qt.LayoutDirection.RightToLeft


class TestCaretSide:
    """Where the caret actually renders, not how the widget is configured.

    Configuration is a poor proxy here: the widget reported AlignRight while
    still laying the text out from the left, because Qt mirrors alignment flags
    inside a right-to-left widget. Only the rendered position tells the truth.
    """

    def _caret_x(self, overlay):
        overlay.show()
        QApplication.processEvents()
        return overlay._text.cursorRect().x(), overlay._text.viewport().width()

    def test_empty_box_puts_the_caret_on_the_right(self, overlay):
        x, width = self._caret_x(overlay)
        assert x > width / 2, f"caret at {x} of {width} — it is on the left"

    def test_persian_text_keeps_the_caret_on_the_right(self, overlay):
        overlay.show()
        overlay._text.setPlainText("سلام")
        QApplication.processEvents()
        assert overlay._text.cursorRect().x() > overlay._text.viewport().width() / 2

    def test_clearing_does_not_flip_it_back(self, overlay):
        overlay.show()
        overlay._text.setPlainText("سلام")
        overlay.clear()
        QApplication.processEvents()
        x, width = overlay._text.cursorRect().x(), overlay._text.viewport().width()
        assert x > width / 2, f"caret at {x} of {width} after clear"
