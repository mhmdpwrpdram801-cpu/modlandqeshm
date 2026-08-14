import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 نصب نیست")

from mlqvoice.app import DEFAULT_DICTIONARY, _explain
from mlqvoice.text import build_lexicon, transform


class TestDefaultDictionary:
    def test_is_valid_json(self):
        # The app writes this file and then reads it back on the next start, so a
        # stray newline inside a string here would break the app after one click.
        json.loads(DEFAULT_DICTIONARY)

    def test_loads_as_a_lexicon_and_its_examples_work(self, tmp_path):
        path = tmp_path / "dictionary.json"
        path.write_text(DEFAULT_DICTIONARY, encoding="utf-8")
        lex = build_lexicon(user_file=path)
        assert transform("کیوب سی تی ال", lex) == "kubectl"
        assert transform("تیلدا اسلش پروژه", lex) == "~/پروژه"


class TestErrorMessages:
    @pytest.mark.parametrize(
        "code", ["not-allowed", "service-not-allowed", "network", "audio-capture"]
    )
    def test_known_codes_get_persian_prose(self, code):
        message = _explain(code)
        assert code not in message  # the raw code is not shown to the user
        assert message.strip()

    def test_unknown_code_is_still_shown_rather_than_swallowed(self):
        assert "something-new" in _explain("something-new")
