"""User settings, validated at load time.

A wrong value here has to fail loudly and early with a message that names the
field — a hotkey the app silently could not parse is indistinguishable, from the
user's chair, from a hotkey that does not work.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .paths import config_file

# Win32 modifier bits (MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN).
MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}

# Virtual-key codes for the keys worth binding to.
VK_CODES: dict[str, int] = {
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "capslock": 0x14,
    "pause": 0x13,
    "scrolllock": 0x91,
    **{f"f{n}": 0x6F + n for n in range(1, 25)},  # F1..F24
    **{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"},
    **{d: ord(d) for d in "0123456789"},
}


class ConfigError(ValueError):
    """A setting the app cannot act on."""


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    vk: int
    label: str

    def __str__(self) -> str:
        return self.label


def parse_hotkey(spec: str) -> Hotkey:
    """``"ctrl+alt+space"`` -> the modifier mask and virtual-key code Win32 wants."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ConfigError("hotkey: خالی است")

    mods = 0
    key: str | None = None
    for part in parts:
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif key is None:
            key = part
        else:
            raise ConfigError(f"hotkey: بیش از یک کلیدِ اصلی دارد ({key!r} و {part!r})")

    if key is None:
        raise ConfigError(f"hotkey: {spec!r} فقط تغییردهنده دارد و کلیدِ اصلی ندارد")
    if key not in VK_CODES:
        raise ConfigError(f"hotkey: کلیدِ {key!r} شناخته نشد")
    if not mods and key not in {f"f{n}" for n in range(1, 25)} | {"pause", "scrolllock"}:
        # Grabbing a bare letter globally would break typing everywhere.
        raise ConfigError(f"hotkey: {spec!r} بدونِ ctrl/alt/shift/win فقط برای کلیدهای F مجاز است")
    return Hotkey(modifiers=mods, vk=VK_CODES[key], label="+".join(parts))


_CHOICES = {
    "digits": ("latin", "fa", "keep"),
    "insert_mode": ("paste", "type"),
}


@dataclass(frozen=True)
class Config:
    hotkey: str = "alt+space"
    lang: str = "fa-IR"
    digits: str = "latin"
    zwnj: bool = True
    glossary: bool = True
    punctuation: bool = True
    interim: bool = True
    insert_mode: str = "paste"
    restore_clipboard: bool = True
    close_after_insert: bool = True
    browser_path: str = ""
    port: int = 0
    _unknown: tuple[str, ...] = field(default=(), repr=False, compare=False)

    def validate(self) -> Hotkey:
        """Check every field; return the parsed hotkey so callers reuse the work."""
        for name, allowed in _CHOICES.items():
            value = getattr(self, name)
            if value not in allowed:
                raise ConfigError(f"{name}: {value!r} نامعتبر است (مجاز: {', '.join(allowed)})")
        if not (0 <= self.port <= 65535):
            raise ConfigError(f"port: {self.port} خارج از بازه است")
        if not self.lang.strip():
            raise ConfigError("lang: خالی است")
        if self.browser_path and not Path(self.browser_path).exists():
            raise ConfigError(f"browser_path: فایلی در {self.browser_path!r} نیست")
        return parse_hotkey(self.hotkey)

    def to_json(self) -> str:
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def from_dict(data: dict) -> Config:
    """Build a config from parsed JSON, keeping note of keys we do not know."""
    known = {f.name for f in fields(Config) if not f.name.startswith("_")}
    unknown = tuple(sorted(set(data) - known))
    return Config(**{k: v for k, v in data.items() if k in known}, _unknown=unknown)


def load(path: Path | None = None) -> Config:
    """Read the config file, falling back to defaults when it does not exist yet."""
    path = path or config_file()
    if not path.exists():
        return Config()
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: فایلِ تنظیمات JSONِ سالم نیست — {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: فایلِ تنظیمات باید یک شیء JSON باشد")
    try:
        return from_dict(data)
    except TypeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def save(cfg: Config, path: Path | None = None) -> Path:
    path = path or config_file()
    path.write_text(cfg.to_json(), encoding="utf-8")
    return path
