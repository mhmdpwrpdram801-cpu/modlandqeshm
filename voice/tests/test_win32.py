import ctypes

import pytest

from mlqvoice.win32 import (
    INPUT,
    KEYBDINPUT,
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    NotWindows,
    kernel32,
    key_input,
    unicode_inputs,
    user32,
)


class TestStructures:
    def test_input_is_the_size_windows_expects(self):
        # SendInput rejects the whole batch if cbSize is wrong, so the union
        # padding has to be right on both 32- and 64-bit builds.
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        assert ctypes.sizeof(INPUT) == expected

    def test_keybdinput_pointer_field_matches_the_word_size(self):
        expected = 24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16
        assert ctypes.sizeof(KEYBDINPUT) == expected

    def test_union_is_reachable_through_the_anonymous_field(self):
        evt = key_input(vk=0x41)
        assert evt.ki.wVk == 0x41


class TestUnicodeInputs:
    def test_ascii_is_one_down_and_one_up(self):
        events = unicode_inputs("a")
        assert len(events) == 2
        assert events[0].ki.wScan == ord("a")
        assert events[0].ki.dwFlags == KEYEVENTF_UNICODE
        assert events[1].ki.dwFlags == KEYEVENTF_UNICODE | KEYEVENTF_KEYUP

    def test_persian_letter_travels_as_its_code_unit(self):
        # The whole point of KEYEVENTF_UNICODE: no Persian keyboard layout needed.
        events = unicode_inputs("ک")
        assert len(events) == 2
        assert events[0].ki.wScan == ord("ک")

    def test_vk_is_zero_so_windows_reads_the_scan_code(self):
        assert unicode_inputs("ی")[0].ki.wVk == 0

    def test_astral_character_is_sent_as_a_surrogate_pair(self):
        # An emoji is two UTF-16 units; splitting them would type garbage.
        events = unicode_inputs("😀")
        assert len(events) == 4
        assert events[0].ki.wScan == 0xD83D
        assert events[2].ki.wScan == 0xDE00


class TestPlatformGuard:
    def test_user32_refuses_off_windows(self):
        import sys

        if sys.platform == "win32":
            pytest.skip("این تست برای بیرونِ ویندوز است")
        with pytest.raises(NotWindows):
            user32()
        with pytest.raises(NotWindows):
            kernel32()
