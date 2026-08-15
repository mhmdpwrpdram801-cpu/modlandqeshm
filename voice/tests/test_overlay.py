"""Overlay behaviour, driven headless.

These exercise the widget itself rather than the functions behind it: the box the
user edits is where a wrong decision (interim text overwriting an edit, the
insert button firing on an empty box) actually shows up.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 نصب نیست")

from PySide6.QtWidgets import QApplication, QPushButton

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

    def test_interim_now_shows_inside_the_box(self, overlay):
        # The owner asked to watch the words appear where they will stay.
        overlay.append_final("سلام")
        overlay.set_interim("دنیا")
        assert overlay.text() == "سلام دنیا"

    def test_a_revised_guess_replaces_the_previous_one(self, overlay):
        # Web Speech rewrites the same phrase over and over. Appending each
        # revision would spell out every guess it ever made.
        overlay.set_interim("دن")
        overlay.set_interim("دنی")
        overlay.set_interim("دنیا")
        assert overlay.text() == "دنیا"

    def test_settled_text_excludes_the_guess(self, overlay):
        overlay.append_final("سلام")
        overlay.set_interim("دنیا")
        assert overlay.settled_text() == "سلام"

    def test_a_guess_never_disturbs_what_came_before_it(self, overlay):
        overlay.append_final("سلام")
        overlay.set_interim("یک")
        overlay.set_interim("دو")
        overlay.set_interim("")
        assert overlay.text() == "سلام"

    def test_a_final_chunk_replaces_the_guess_rather_than_following_it(self, overlay):
        overlay.set_interim("در حالِ گفتن")
        overlay.append_final("گفتم")
        assert overlay.text() == "گفتم"

    def test_clear_empties_the_box(self, overlay):
        overlay.append_final("سلام")
        overlay.set_interim("دنیا")
        overlay.clear()
        assert overlay.text() == ""

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

    def test_stopping_drops_the_half_finished_guess(self, overlay):
        # Nobody is listening any more, so a guess that will never be confirmed
        # has no business sitting in the box looking like text.
        overlay.append_final("سلام")
        overlay.set_interim("نیمه‌کاره")
        overlay.set_recording(False)
        assert overlay.text() == "سلام"

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

    def test_begin_session_clears_a_leftover_guess_too(self, overlay):
        overlay.set_interim("حدسِ نیمه‌کاره")
        overlay.begin_session("Notepad")
        assert overlay.text() == ""

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


class TestButtons:
    """The owner asked for fewer of them."""

    def test_the_finglish_button_is_gone(self, overlay):
        # Typing converts itself now, so a button for it was one more thing to
        # look at and never press.
        assert not hasattr(overlay, "_finglish")
        labels = [b.text() for b in overlay.findChildren(QPushButton)]
        assert not any("فارسی" in label for label in labels)

    def test_the_primary_button_is_one_action_not_two(self, overlay):
        # "توقف" then "بنویس" became a single "تمام شد".
        assert overlay._insert.text() == "تمام شد"

    def test_set_text_replaces_the_whole_box(self, overlay):
        overlay.append_final("salam")
        overlay.set_text("سلام")
        assert overlay.text() == "سلام"

    def test_the_hint_names_the_one_shortcut_that_matters(self, overlay):
        assert "Ctrl+Enter" in overlay._hint.text()

    def test_the_hint_no_longer_advertises_a_button_that_is_gone(self, overlay):
        assert "Ctrl+L" not in overlay._hint.text()


class TestGuessAndEditingTogether:
    """The reason the guess is a tracked tail and not just appended text.

    Web Speech revises the same phrase many times a second. The box is also
    where the user fixes things. Those two have to share it without the guess
    ever eating an edit.
    """

    def test_an_edit_further_back_survives_the_next_revision(self, overlay):
        overlay.append_final("سلام")
        overlay.set_interim("دنیا")
        # The user fixes the settled word while the guess is still moving.
        cursor = overlay._text.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(4, cursor.MoveMode.KeepAnchor)
        cursor.insertText("درود")
        overlay.set_interim("دنیای")
        assert overlay.text() == "درود دنیای"

    def test_the_caret_is_not_dragged_to_the_end_by_a_revision(self, overlay):
        overlay.append_final("سلام دنیا")
        cursor = overlay._text.textCursor()
        cursor.setPosition(2)
        overlay._text.setTextCursor(cursor)
        overlay.set_interim("چطوری")
        assert overlay._text.textCursor().position() == 2

    def test_an_empty_guess_removes_the_tail_entirely(self, overlay):
        overlay.append_final("سلام")
        overlay.set_interim("دنیا")
        overlay.set_interim("")
        assert overlay.text() == "سلام"

    def test_a_guess_on_an_empty_box_needs_no_leading_space(self, overlay):
        overlay.set_interim("سلام")
        assert overlay._text.toPlainText() == "سلام"

    def test_repeated_revisions_do_not_accumulate(self, overlay):
        for guess in ("ی", "یک", "یکی", "یکی از"):
            overlay.set_interim(guess)
        assert overlay.text() == "یکی از"

    def test_pressing_done_mid_guess_writes_what_is_on_screen(self, overlay):
        # WYSIWYG: the guess is visible, so it is part of what "تمام شد" means.
        got = []
        overlay.insertRequested.connect(got.append)
        overlay.append_final("سلام")
        overlay.set_interim("دنیا")
        overlay._emit_insert()
        assert got == ["سلام دنیا"]

    def test_the_insert_button_wakes_up_for_a_guess_alone(self, overlay):
        # Pressing "تمام شد" mid-sentence should write what is on screen, so the
        # button cannot be disabled just because nothing is final yet.
        overlay.set_interim("سلام")
        assert overlay._insert.isEnabled()
