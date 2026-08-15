"""Typing Finglish and getting Persian, without pressing anything.

The owner's words: they want it to behave like Google Translate's Persian input
— type Latin, get Persian — but **without the candidate box**. So there is no
picker: the word is converted the moment it ends, and Ctrl+Z is the way back.

Every test here sends a real key event through the widget rather than calling
the conversion directly. That is the whole point: the earlier version worked
perfectly when called as a function and still needed a button press to happen.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 نصب نیست")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from mlqvoice.text import build_lexicon, finglish_to_persian
from mlqvoice.ui.overlay import Overlay


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def convert():
    skip = build_lexicon().outputs()
    return lambda word: finglish_to_persian(word, skip=skip)


class Spy:
    """A transliterator that records what it was asked to convert."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, word: str) -> str:
        self.calls.append(word)
        return word


@pytest.fixture
def spy():
    return Spy()


def _boom(_word: str) -> str:
    raise RuntimeError("مبدل خراب است")


@pytest.fixture
def box(qt_app, convert):
    w = Overlay()
    w.set_transliterator(convert)
    yield w
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def press(widget, key: Qt.Key, text: str = "") -> None:
    """A real key event, delivered the way the keyboard delivers one."""
    event = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
    QApplication.sendEvent(widget._text, event)


def typewrite(widget, phrase: str) -> None:
    """Type *phrase* one character at a time, spaces included."""
    for ch in phrase:
        if ch == " ":
            press(widget, Qt.Key.Key_Space, " ")
        elif ch == "\n":
            press(widget, Qt.Key.Key_Return, "\r")
        else:
            press(widget, Qt.Key.Key_A, ch)  # key code is irrelevant; text is not


class TestItConvertsAsYouType:
    def test_a_word_turns_persian_on_the_space(self, box):
        typewrite(box, "salam ")
        assert box._text.toPlainText() == "سلام "

    def test_a_whole_sentence(self, box):
        typewrite(box, "salam chetori ")
        assert box._text.toPlainText() == "سلام چطوری "

    def test_the_last_word_converts_on_enter_too(self, box):
        typewrite(box, "salam\n")
        assert box._text.toPlainText().startswith("سلام")

    def test_nothing_happens_until_the_word_ends(self, box):
        # Mid-word there is nothing to convert yet — this is the "no candidate
        # box" part of the request: no half-guesses shown while typing.
        typewrite(box, "salam")
        assert box._text.toPlainText() == "salam"

    def test_persian_typed_directly_is_left_alone(self, box):
        typewrite(box, "سلام ")
        assert box._text.toPlainText() == "سلام "

    def test_a_second_word_does_not_disturb_the_first(self, box):
        typewrite(box, "ketab ro ")
        assert box._text.toPlainText() == "کتاب رو "


class TestCodeSurvives:
    """The reason "." is not a word boundary."""

    @pytest.mark.parametrize("token", ["app.py", "user_id", "utf-8", "README.md", "x=5"])
    def test_code_shaped_tokens_are_untouched(self, box, token):
        typewrite(box, token + " ")
        assert box._text.toPlainText() == token + " "

    def test_the_dot_alone_does_not_trigger_a_conversion(self, box):
        # If "." ended a word, "app" would be converted before the guard ever
        # saw that the whole token was code.
        typewrite(box, "app.")
        assert box._text.toPlainText() == "app."

    def test_glossary_output_is_untouched(self, box):
        # Typing `commit` in a programmer's tool means `commit`.
        typewrite(box, "commit ")
        assert box._text.toPlainText() == "commit "


class TestDictationIsNeverTouched:
    """The guarantee the glossary depends on, kept intact.

    Asserting on the *text* is not enough and the first version of this class
    made exactly that mistake: dictated output is full of glossary words, which
    the skip-list leaves alone anyway, so the text came out identical whether
    the transliterator ran or not. The tests passed with the guarantee broken.

    So these watch whether it is **called at all**.
    """

    def test_appending_never_calls_the_transliterator(self, box, spy):
        box.set_transliterator(spy)
        box.append_final("commit کن")
        assert spy.calls == []

    def test_set_text_never_calls_it(self, box, spy):
        box.set_transliterator(spy)
        box.set_text("database migration")
        assert spy.calls == []

    def test_and_typing_still_does(self, box, spy):
        # The control: proves the spy would have noticed.
        box.set_transliterator(spy)
        typewrite(box, "salam ")
        assert spy.calls == ["salam"]

    def test_dictation_arriving_mid_typing_is_still_safe(self, box):
        # The state that matters, and the first version of this test never built
        # it: type first (which arms the conversion), *then* let a dictated
        # phrase land, then press space. Without the reset, the dictated word is
        # the one sitting behind the caret and it gets rewritten.
        typewrite(box, "salam")
        box.append_final("mishe")
        press(box, Qt.Key.Key_Space, " ")
        assert box._text.toPlainText() == "salam mishe "

    def test_replacing_the_box_mid_typing_is_safe_too(self, box):
        typewrite(box, "salam")
        box.set_text("mishe")
        press(box, Qt.Key.Key_Space, " ")
        assert box._text.toPlainText() == "mishe "

    def test_typing_onto_the_end_of_a_dictated_word_converts_only_the_typed_part(self, box):
        # A real edit: dictation produced a word and the user extends it. Only
        # the characters they added are theirs to convert — without the floor,
        # the conversion swallows the dictated stem along with them.
        box.append_final("mishe")
        typewrite(box, "tar ")
        assert box._text.toPlainText() == "mishe" + "تر" + " "


class TestSwitchedOff:
    def test_without_a_transliterator_typing_is_untouched(self, qt_app):
        w = Overlay()  # none set, which is what live_finglish: false produces
        typewrite(w, "salam ")
        assert w._text.toPlainText() == "salam "
        w.close()
        w.deleteLater()

    def test_it_can_be_switched_off_again(self, box):
        box.set_transliterator(None)
        typewrite(box, "salam ")
        assert box._text.toPlainText() == "salam "


class TestNeverGetsInTheWay:
    def test_a_broken_transliterator_does_not_break_typing(self, qt_app):
        # Losing a conversion is a nuisance; losing the keystroke is a bug.
        w = Overlay()
        w.set_transliterator(_boom)
        typewrite(w, "salam ")
        assert w._text.toPlainText() == "salam "
        w.close()
        w.deleteLater()

    def test_and_the_failure_does_not_escape_into_qt(self, qt_app, monkeypatch):
        # Asserting on the text alone did not discriminate: the keystroke lands
        # either way. What differs is whether the exception climbs out of
        # eventFilter, which Qt reports through the excepthook — and which, in
        # a packaged build, is the difference between a nuisance and a crash.
        seen = []
        monkeypatch.setattr(sys, "excepthook", lambda *info: seen.append(info))
        w = Overlay()
        w.set_transliterator(_boom)
        typewrite(w, "salam ")
        QApplication.processEvents()
        w.close()
        w.deleteLater()
        assert seen == []

    def test_one_undo_puts_the_latin_back(self, box):
        # The escape hatch that replaces Google's candidate box.
        typewrite(box, "salam ")
        assert box._text.toPlainText() == "سلام "
        box._text.undo()
        assert "salam" in box._text.toPlainText()

    def test_a_space_at_the_start_of_the_box_is_harmless(self, box):
        press(box, Qt.Key.Key_Space, " ")
        assert box._text.toPlainText() == " "

    def test_typing_over_a_selection_is_left_alone(self, box):
        # Typed first, so the conversion is genuinely armed — otherwise this
        # test passes on the early-return above and proves nothing about the
        # selection guard at all.
        typewrite(box, "salam")
        box._text.selectAll()
        press(box, Qt.Key.Key_Space, " ")
        assert box._text.toPlainText() == " "
