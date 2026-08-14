"""Command line.

``mlqvoice`` with no arguments runs the app.  The subcommands exist so the
dictionary can be exercised without a microphone — "say this sentence and show
me what you would type" is the fastest way to test a new word, and it works on
any platform, which is also how the test suite reaches this code.
"""

from __future__ import annotations

import argparse
import contextlib
import sys

from . import APP_NAME, __version__
from .config import ConfigError, load, parse_hotkey
from .paths import config_file, data_dir, user_dictionary_file
from .text import build_lexicon, transform
from .text.pipeline import Options


def force_utf8() -> None:
    """Make the output streams able to carry Persian.

    Windows picks the process ANSI code page for stdout — cp1252 on a US
    install — and *every* Persian ``print`` in this CLI then dies with
    ``UnicodeEncodeError``.  It is not hypothetical: this crashed on the first
    CI run on a real Windows machine, on the very first line of ``check``.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # A stream that refuses is still better than crashing the command.
        with contextlib.suppress(ValueError, OSError, AttributeError):
            reconfigure(encoding="utf-8", errors="replace")


def _options(cfg) -> Options:
    return Options(
        digits=cfg.digits, zwnj=cfg.zwnj, glossary=cfg.glossary, punctuation=cfg.punctuation
    )


def cmd_say(args) -> int:
    """Run text through the same pipeline live speech goes through."""
    cfg = load()
    text = " ".join(args.words) if args.words else sys.stdin.read()
    lex = build_lexicon(
        glossary=cfg.glossary, punctuation=cfg.punctuation, user_file=user_dictionary_file()
    )
    print(transform(text, lex, _options(cfg)))
    return 0


def cmd_paths(_args) -> int:
    print(f"تنظیمات:  {config_file()}")
    print(f"دیکشنری:  {user_dictionary_file()}")
    print(f"پوشه:     {data_dir()}")
    return 0


def cmd_check(_args) -> int:
    """Validate the config and report what the app would do with it."""
    try:
        cfg = load()
        hotkey = cfg.validate()
    except ConfigError as exc:
        print(f"تنظیمات ایراد دارد: {exc}", file=sys.stderr)
        return 1

    lex = build_lexicon(
        glossary=cfg.glossary, punctuation=cfg.punctuation, user_file=user_dictionary_file()
    )
    print(f"{APP_NAME} {__version__}")
    print(f"کلیدِ میان‌بُر: {hotkey}")
    print(f"زبان:         {cfg.lang}")
    print(f"ارقام:        {cfg.digits}")
    print(f"نوشتن:        {cfg.insert_mode}")
    print(f"واژه‌ها:       {len(lex)}")
    if cfg._unknown:
        print(f"کلیدهای ناشناخته در تنظیمات: {', '.join(cfg._unknown)}", file=sys.stderr)
    return 0


def cmd_selftest(_args) -> int:
    """Build every heavy part of the app once, without opening anything.

    This exists for the packaged exe.  ``check`` and ``say`` never touch Qt, so
    they pass happily even if PySide6 or its platform plugins failed to make it
    into the bundle — and the user is left with an icon that does nothing when
    double-clicked.  Constructing the real widgets is what proves otherwise.
    """
    from PySide6.QtWidgets import QApplication

    from .bridge import RecognizerBridge
    from .ui.fonts import FAMILY, available, load_fonts
    from .ui.overlay import Overlay
    from .ui.tray import make_icon

    app = QApplication.instance() or QApplication([])
    plugin = app.platformName()

    # The font is a bundled data file like the dictionaries; if --add-data missed
    # it the app still runs, just ugly — exactly the kind of silent regression
    # this command exists to catch.
    load_fonts()
    if not available():
        print(f"selftest: فونتِ {FAMILY} همراهِ بسته نشده", file=sys.stderr)
        return 1

    overlay = Overlay()
    overlay.append_final("آزمایش")
    if overlay.text() != "آزمایش":
        print("selftest: کادر متن را نگه نداشت", file=sys.stderr)
        return 1
    if make_icon().isNull():
        print("selftest: آیکنِ سینی ساخته نشد", file=sys.stderr)
        return 1

    page = RecognizerBridge().page_html()
    if "webkitSpeechRecognition" not in page:
        print("selftest: صفحه‌ی تشخیصِ گفتار همراهِ بسته نشده", file=sys.stderr)
        return 1

    lex = build_lexicon(user_file=user_dictionary_file())
    print(
        f"selftest ok — Qt platform={plugin}، فونت={FAMILY}، "
        f"صفحه={len(page)} بایت، واژه‌ها={len(lex)}"
    )
    return 0


def cmd_hotkey(args) -> int:
    try:
        hk = parse_hotkey(args.spec)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{hk}  (modifiers=0x{hk.modifiers:04x}, vk=0x{hk.vk:02x})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="گفتار به متن، برای برنامه‌نویس‌ها")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command")

    say = sub.add_parser("say", help="متن را از دیکشنری رد کن و نتیجه را چاپ کن")
    say.add_argument("words", nargs="*", help="اگر ندهی، از ورودیِ استاندارد می‌خواند")
    say.set_defaults(func=cmd_say)

    sub.add_parser("paths", help="مسیرِ تنظیمات و دیکشنری").set_defaults(func=cmd_paths)
    sub.add_parser("check", help="وارسیِ تنظیمات").set_defaults(func=cmd_check)
    sub.add_parser("selftest", help="ساختِ یک‌بارِ رابط — برای وارسیِ خودِ exe").set_defaults(
        func=cmd_selftest
    )

    hotkey = sub.add_parser("hotkey", help="یک ترکیبِ کلید را بسنج")
    hotkey.add_argument("spec")
    hotkey.set_defaults(func=cmd_hotkey)
    return parser


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    args = build_parser().parse_args(argv)
    if getattr(args, "func", None) is not None:
        return args.func(args)

    from .app import run  # imported late so the subcommands need no Qt

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
