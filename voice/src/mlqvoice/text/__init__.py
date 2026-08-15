"""Text stages: normalisation, the spoken-form lexicon, and the pipeline."""

from .finglish import convert as finglish_to_persian
from .finglish import has_latin
from .lexicon import Entry, Lexicon, build_lexicon, spoken_key
from .normalize import ZWNJ, normalize, strip_zwnj
from .pipeline import Options, render, transform, transform_hits

__all__ = [
    "ZWNJ",
    "Entry",
    "Lexicon",
    "Options",
    "build_lexicon",
    "finglish_to_persian",
    "has_latin",
    "normalize",
    "render",
    "spoken_key",
    "strip_zwnj",
    "transform",
    "transform_hits",
]
