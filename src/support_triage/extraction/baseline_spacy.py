"""Traditional-NLP baseline (spaCy NER) for comparison against the NL API.

spaCy runs locally and for free, so it is the natural traditional baseline for
the managed Cloud Natural Language API. ``extract_spacy`` emits the SAME entity
schema as the NL API path (``name, type, salience, entity_sentiment_*``) so the
two extractors can be scored with the identical entity/tag-overlap metric -
see ``support_triage.eval.run.entity_tag_overlap_spacy`` and ``make baseline``.

spaCy's small model has no salience or per-entity sentiment, so salience is the
same mention-count proxy used by the Phase-1 NL API path and the sentiment
fields are ``None``. Choice recorded in docs/adr/0002-nl-api-vs-llm-extraction.md.
"""

from __future__ import annotations

from functools import lru_cache

# spaCy's fine-grained labels mapped onto the coarse types the NL API emits, so
# the two extractors are comparable. Unmapped labels keep their spaCy label.
_TYPE_MAP = {
    "PERSON": "PERSON",
    "ORG": "ORGANIZATION",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "FAC": "LOCATION",
    "DATE": "DATE",
    "TIME": "DATE",
    "MONEY": "PRICE",
    "QUANTITY": "NUMBER",
    "CARDINAL": "NUMBER",
    "ORDINAL": "NUMBER",
    "PERCENT": "NUMBER",
    "PRODUCT": "CONSUMER_GOOD",
    "EVENT": "EVENT",
    "WORK_OF_ART": "WORK_OF_ART",
    "LAW": "OTHER",
    "LANGUAGE": "OTHER",
    "NORP": "OTHER",
}


@lru_cache(maxsize=1)
def _nlp():
    """Load en_core_web_sm once per process (installed by `make env`)."""
    import spacy

    return spacy.load("en_core_web_sm", disable=["lemmatizer"])


def extract_spacy(text: str) -> list[dict]:
    """Run spaCy en_core_web_sm NER, returning entities in the same shape as the
    NL API path so the two can be compared directly.

    Entities are deduped by (name, type); ``salience`` is a mention-count proxy
    normalised to sum to 1 (spaCy gives no salience), and the per-entity
    sentiment fields are ``None`` (the small model has no sentiment). Returned
    most prominent first.
    """
    doc = _nlp()(text or "")
    counts: dict[tuple[str, str], int] = {}
    for ent in doc.ents:
        name = ent.text.strip()
        if not name:
            continue
        key = (name, _TYPE_MAP.get(ent.label_, ent.label_))
        counts[key] = counts.get(key, 0) + 1

    total = sum(counts.values()) or 1
    out = [
        {
            "name": name,
            "type": etype,
            "salience": round(c / total, 4),
            "entity_sentiment_score": None,
            "entity_sentiment_magnitude": None,
        }
        for (name, etype), c in counts.items()
    ]
    return sorted(out, key=lambda d: d["salience"], reverse=True)
