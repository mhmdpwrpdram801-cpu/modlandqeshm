"""Command line.

``mlqvoice`` with no arguments runs the app.  The subcommands exist so the
dictionary can be exercised without a microphone — "say this sentence and show
me what you would type" is the fastest way to test a new word, and it works on
any platform, which is also how the test suite reaches this code.
"""

from __future__ import annotations

import argparse
import sys

from . import APP_NAME, __version__
from .config import ConfigError, load, parse_hotkey
from .paths import config_file, data_dir, user_dictionary_file
from .text import build_lexicon, transform
from .text.pipeline import Options


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

    hotkey = sub.add_parser("hotkey", help="یک ترکیبِ کلید را بسنج")
    hotkey.add_argument("spec")
    hotkey.set_defaults(func=cmd_hotkey)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "func", None) is not None:
        return args.func(args)

    from .app import run  # imported late so the subcommands need no Qt

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
