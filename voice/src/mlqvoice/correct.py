"""Second-guessing the recogniser with Gemini.

Why this exists at all, and why it is not a spell checker: what Google's
``fa-IR`` recogniser gets wrong is almost never *spelling*. It emits real,
correctly-spelled Persian words — just the wrong ones («کاربر» where you said
«کاربرد»). A dictionary cannot see that, because both entries are in it. Only
something that reads the sentence can.

Measured, before writing any of this: Google Translate's public spell endpoint
(``dt=sp`` on ``client=gtx``) returns no correction at all — not for Persian,
and not for ``helo wrold`` either. The README had recorded it as a Persian
limitation; the probe simply never worked. So "Google's spell checker" in the
usable sense is Gemini.

Three rules this module will not break, in order of how badly they hurt:

1. **The user's sentence is never lost.** Every failure path — no key, no
   network, timeout, refusal, garbage — returns the original text. The caller
   cannot tell the difference except that nothing improved.
2. **It corrects, it does not rewrite.** A model asked to "improve" Persian
   will happily reword it. The prompt forbids that and :func:`_plausible`
   throws away anything that came back looking like an essay instead of an
   edit.
3. **It runs before the glossary, never after.** By the time the pipeline is
   done, «کامیت کن نقطه» has become ``commit .`` — and a language model shown
   that will "fix" it back into a sentence. Correcting the raw Persian first
   sidesteps the whole problem.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

DEFAULT_MODEL = "gemini-2.0-flash"

#: Anything longer is a paragraph, not a dictated sentence, and paying to have
#: a model reread it is not worth the wait.
MAX_CHARS = 2000

INSTRUCTION = (
    "تو یک ویراستارِ متنِ فارسی هستی که خروجیِ تبدیلِ گفتار به متن را اصلاح می‌کند.\n"
    "فقط غلط‌های املایی و کلماتی را که اشتباه شنیده شده‌اند درست کن.\n"
    "قواعد سخت:\n"
    "- جمله را بازنویسی نکن، خلاصه نکن، و چیزی به آن اضافه نکن.\n"
    "- لحن و انتخابِ کلماتِ نویسنده را عوض نکن.\n"
    "- اگر متن درست است، عیناً همان را برگردان.\n"
    "- هیچ توضیحی ننویس. فقط خودِ متنِ اصلاح‌شده را برگردان.\n"
    "- کلماتِ انگلیسی و علائم را دست نزن.\n"
)


class Corrector:
    """One Gemini call, wrapped in everything that can go wrong."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        timeout: float = 6.0,
        opener=None,
    ) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        # Injected in tests so no test ever reaches the network. Production
        # leaves it None and uses urllib.
        self._opener = opener

    @property
    def enabled(self) -> bool:
        return bool(self.api_key.strip())

    def correct(self, text: str) -> str:
        """Return *text* corrected, or *text* itself if anything at all fails."""
        original = text
        if not self.enabled or not text.strip() or len(text) > MAX_CHARS:
            return original
        try:
            reply = self._ask(text)
        except Exception as exc:
            # Deliberately broad. This runs on a worker thread while the user
            # waits for their sentence; there is no failure here worth turning
            # into a lost dictation, and urllib alone can raise half a dozen
            # unrelated types before the reply is even parsed.
            log.warning("correction failed, keeping the original: %s", exc)
            return original
        return reply if _plausible(original, reply) else original

    # -- internals -------------------------------------------------------

    def _ask(self, text: str) -> str:
        body = json.dumps(
            {
                "system_instruction": {"parts": [{"text": INSTRUCTION}]},
                "contents": [{"parts": [{"text": text}]}],
                "generationConfig": {
                    # Correction is not a creative task: the same sentence
                    # should come back the same way every time.
                    "temperature": 0,
                    "candidateCount": 1,
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            ENDPOINT.format(model=self.model),
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                # In the header, never the URL: query strings end up in proxy
                # logs and crash reports.
                "x-goog-api-key": self.api_key,
            },
        )
        opener = self._opener or urllib.request.urlopen
        with opener(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return _extract(payload)


def _extract(payload: dict) -> str:
    """Pull the text out of a Gemini reply, tolerating a shape we did not expect."""
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    return _unfence(text).strip()


def _unfence(text: str) -> str:
    """Drop a ```…``` wrapper if the model added one despite being told not to."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    if len(lines) < 2:
        return text
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body)


def _plausible(original: str, reply: str) -> bool:
    """Is *reply* an edit of *original*, or did the model write something else?

    The failure this guards against is specific and has a cost: a model that
    decides to be helpful returns an explanation, a translation, or a politely
    expanded version — and that would be typed straight into the user's
    document. Length is a blunt test but it separates "fixed two words" from
    "wrote a paragraph" reliably, and a wrong rejection costs nothing but a
    missed correction.
    """
    if not reply.strip():
        return False
    # A dictated line that comes back as several is a sign the model answered
    # rather than edited.
    if "\n" in reply and "\n" not in original:
        return False
    low, high = len(original) * 0.5, len(original) * 1.6
    return low <= len(reply) <= high
