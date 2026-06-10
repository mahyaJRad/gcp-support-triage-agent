"""Traditional-NLP baseline (spaCy NER) for comparison against the NL API."""

from __future__ import annotations


def extract_spacy(text: str) -> list[dict]:
    """Run spaCy en_core_web_sm NER, returning entities in the same shape as the
    NL API path so the two can be compared directly."""
    raise NotImplementedError
