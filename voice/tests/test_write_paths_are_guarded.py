"""Every path that writes on the user's behalf, and how it fails.

Three separate bugs found in one audit, all of the same shape: a write that can
fail in a way nobody had arranged to hear about.

1. ``_apply_learned`` caught only ``DictionaryUnreadable``. A full disk or a
   locked file raised ``OSError`` straight out of a Qt slot — while its two
   siblings, ``_learn_from`` and ``_count``, both guard for exactly that.
2. ``insert`` emptied the clipboard before the ``try`` that restores it, so a
   refused ``SetClipboardData`` left the user with **nothing** where their copied
   text had been.
3. Nothing was written atomically: ``write_text`` truncates first, so an
   interrupted write leaves a half file. Two of the three files tolerate that;
   ``dictionary.json`` is fatal, which is what made it worth fixing.
"""

from __future__ import annotations

import json

import pytest

from mlqvoice import inject
from mlqvoice.paths import write_atomic
from mlqvoice.text import learning
from mlqvoice.text.learning import Suggestion

SUGGESTIONS = [Suggestion(spoken="کاربر", replacement="کاربرد", count=3)]


class TestApplyingLearnedEntries:
    @pytest.fixture
    def paths(self, monkeypatch, tmp_path):
        learned = tmp_path / "learned.json"
        words = tmp_path / "dictionary.json"
        monkeypatch.setattr("mlqvoice.app.learned_file", lambda: learned)
        monkeypatch.setattr("mlqvoice.app.user_dictionary_file", lambda: words)
        learning.save(learned, SUGGESTIONS)
        return learned, words

    def agree(self, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        )

    def test_a_write_that_cannot_happen_is_reported_not_raised(self, app, paths, monkeypatch):
        # A directory where the file should be is the cheap way to make the
        # write fail for a reason that is not about JSON at all.
        _learned, words = paths
        words.mkdir()
        self.agree(monkeypatch)
        said: list[str] = []
        monkeypatch.setattr(
            type(app.tray), "showMessage", lambda _s, _t, msg, *a, **k: said.append(msg)
        )
        app._apply_learned()  # must not raise out of the slot
        assert said and "دیکشنری" in said[0]

    def test_and_the_lexicon_is_left_exactly_as_it_was(self, app, paths, monkeypatch):
        _learned, words = paths
        words.mkdir()
        self.agree(monkeypatch)
        monkeypatch.setattr(type(app.tray), "showMessage", lambda *a, **k: None)
        before = len(app.lexicon)
        app._apply_learned()
        assert len(app.lexicon) == before


class TestTheClipboardIsPutBack:
    def test_a_failed_write_does_not_cost_the_user_their_clipboard(self, monkeypatch):
        """The worst version of this bug: the copy is gone and nothing says so.

        ``set_clipboard_text`` empties the clipboard before it writes, so a
        refusal halfway through used to leave it blank — and the restore lived
        after that call, where an exception never reached it.
        """
        restored: list[str] = []
        calls = {"n": 0}

        def flaky(text: str) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise inject.InjectError("نوشتن در کلیپ‌بورد رد شد")
            restored.append(text)

        monkeypatch.setattr(inject, "focus_window", lambda *a, **k: True)
        monkeypatch.setattr(inject, "get_clipboard_text", lambda: "چیزی که کاربر کپی کرده بود")
        monkeypatch.setattr(inject, "set_clipboard_text", flaky)
        monkeypatch.setattr(inject, "press_ctrl_v", lambda: None)

        with pytest.raises(inject.InjectError):
            inject.insert(1234, "متنِ تازه", settle=0)
        assert restored == ["چیزی که کاربر کپی کرده بود"]

    def test_the_ordinary_path_still_restores_once(self, monkeypatch):
        seen: list[str] = []
        monkeypatch.setattr(inject, "focus_window", lambda *a, **k: True)
        monkeypatch.setattr(inject, "get_clipboard_text", lambda: "قبلی")
        monkeypatch.setattr(inject, "set_clipboard_text", seen.append)
        monkeypatch.setattr(inject, "press_ctrl_v", lambda: None)
        monkeypatch.setattr(inject.time, "sleep", lambda _s: None)

        inject.insert(1234, "متنِ تازه", settle=0)
        assert seen == ["متنِ تازه", "قبلی"]


class TestWritesAreAtomic:
    def test_a_failed_replace_leaves_the_original_untouched(self, monkeypatch, tmp_path):
        """The property that matters: never a half file where a whole one was.

        ``write_text`` truncates before it writes, so an interruption leaves the
        file shorter than it was — and for ``dictionary.json`` a short file is a
        broken one, which used to stop the app from starting at all.
        """
        import os

        path = tmp_path / "dictionary.json"
        original = json.dumps({"terms": {"nginx": ["ان جین ایکس"]}}, ensure_ascii=False)
        path.write_text(original, encoding="utf-8")

        monkeypatch.setattr(os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("قطع شد")))
        with pytest.raises(OSError):
            write_atomic(path, "محتوای تازه")
        assert path.read_text(encoding="utf-8") == original

    def test_and_no_scratch_file_is_left_behind(self, monkeypatch, tmp_path):
        import os

        path = tmp_path / "dictionary.json"
        path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("قطع شد")))
        with pytest.raises(OSError):
            write_atomic(path, "x")
        assert list(tmp_path.iterdir()) == [path]

    def test_the_bytes_are_on_disk_before_the_rename(self, monkeypatch, tmp_path):
        """Two mechanisms, neither observable from the result alone.

        A test cannot pull the power cord, so these are pinned by watching the
        calls instead. Without the ``fsync`` the rename can land before the
        content does, and the machine comes back up holding a file that exists
        and is empty — the worst of both worlds, because it *looks* written.
        """
        import os

        order: list[str] = []
        real_fsync, real_replace = os.fsync, os.replace
        monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
        monkeypatch.setattr(
            os, "replace", lambda a, b: (order.append("replace"), real_replace(a, b))[1]
        )
        write_atomic(tmp_path / "f.json", "x")
        assert order == ["fsync", "replace"]

    def test_the_scratch_file_shares_the_target_directory(self, monkeypatch, tmp_path):
        """``os.replace`` is only atomic inside one filesystem.

        The obvious shortcut — a temp file in ``%TEMP%`` — puts it on whatever
        drive Windows put the temp directory on, which is regularly not the one
        holding ``%APPDATA%``. The rename then fails outright.
        """
        import tempfile as tf

        seen: list[str] = []
        real = tf.mkstemp
        monkeypatch.setattr(tf, "mkstemp", lambda **kw: (seen.append(kw.get("dir")), real(**kw))[1])
        target = tmp_path / "sub" / "f.json"
        write_atomic(target, "x")
        assert seen == [str(target.parent)]

    def test_a_successful_write_lands_whole(self, tmp_path):
        path = tmp_path / "f.json"
        write_atomic(path, "سلام\n")
        assert path.read_text(encoding="utf-8") == "سلام\n"
        assert list(tmp_path.iterdir()) == [path]

    @pytest.mark.parametrize(
        "writer",
        [
            "mlqvoice.config.save",
            "mlqvoice.text.learning.save",
            "mlqvoice.text.learning.apply_to_dictionary",
            "mlqvoice.text.stats.save",
        ],
    )
    def test_every_writer_goes_through_it(self, writer):
        # Pinned by name rather than behaviour on purpose: a new writer added
        # later that calls write_text directly is the regression this catches.
        import importlib
        import inspect

        module_name, func_name = writer.rsplit(".", 1)
        func = getattr(importlib.import_module(module_name), func_name)
        source = inspect.getsource(func)
        assert "write_atomic" in source, f"{writer} هنوز مستقیم write_text می‌کند"
        assert ".write_text(" not in source, f"{writer} هنوز write_text دارد"
