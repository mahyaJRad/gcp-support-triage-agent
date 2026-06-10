"""Entity and sentiment extraction via the Cloud Natural Language API.

Two phases, selected by ``entity_sentiment``:

* **Phase 1** - v2 ``analyze_entities`` (no salience field, so prominence is a
  mention-count proxy) + v2 ``analyze_sentiment`` for document sentiment.
* **Phase 2** - v1 ``analyze_entity_sentiment`` (real salience *and* per-entity
  sentiment in one call) + ``analyze_sentiment`` for document sentiment.

Both paths cost 2 NL units per (<=1k-char) document. Per-document failures are
logged and skipped; the batch never crashes.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from support_triage.config import CONFIG
from support_triage.gcp import with_backoff

log = logging.getLogger("support_triage")


@dataclass
class Extraction:
    """Per-ticket extraction result.

    Entities are ``[{name, type, salience, entity_sentiment_score,
    entity_sentiment_magnitude}]`` (the two sentiment fields are ``None`` in
    Phase 1). ``units`` is the NL units this document consumed.
    """

    ticket_id: int
    entities: list[dict]
    sentiment_score: float
    sentiment_magnitude: float
    units: int


def _units(text: str) -> int:
    """NL units for one feature call: 1 unit per (partial) 1,000 chars, min 1."""
    return max(1, math.ceil(len(text) / CONFIG.nl_unit_chars))


def _entities_with_sentiment(client, doc) -> list[dict]:
    """Phase 2: v1 analyze_entity_sentiment -> real salience + entity sentiment."""
    resp = with_backoff(client.analyze_entity_sentiment, request={"document": doc})
    out = [
        {
            "name": e.name,
            "type": e.type_.name,
            "salience": round(e.salience, 4),
            "entity_sentiment_score": round(e.sentiment.score, 4),
            "entity_sentiment_magnitude": round(e.sentiment.magnitude, 4),
        }
        for e in resp.entities
    ]
    return sorted(out, key=lambda d: d["salience"], reverse=True)


def _entities_mention_proxy(client, doc) -> list[dict]:
    """Phase 1: v2 analyze_entities; approximate salience from mention counts.

    The v2 API omits salience, so each entity's prominence is its mention count
    normalized to sum to 1 across the document, preserving the relative ranking.
    Entities are returned most prominent first; no per-entity sentiment.
    """
    entities = with_backoff(client.analyze_entities, request={"document": doc}).entities
    counts = [max(len(e.mentions), 1) for e in entities]
    total = sum(counts) or 1
    out = [
        {
            "name": e.name,
            "type": e.type_.name,
            "salience": round(c / total, 4),
            "entity_sentiment_score": None,
            "entity_sentiment_magnitude": None,
        }
        for e, c in zip(entities, counts, strict=True)
    ]
    return sorted(out, key=lambda d: d["salience"], reverse=True)


def make_client(entity_sentiment: bool):
    """Return an NL API client for the requested phase (v1 for Phase 2, else v2).

    entity_sentiment lives only in v1; v1 also serves analyze_sentiment, so a
    single client covers both calls per document.
    """
    if entity_sentiment:
        from google.cloud import language_v1 as language
    else:
        from google.cloud import language_v2 as language
    return language.LanguageServiceClient(), language


def extract_one(client, language, ticket_id: int, text: str, entity_sentiment: bool) -> Extraction:
    """Extract entities + document sentiment for one ticket (2 NL units)."""
    doc = language.Document(content=text, type_=language.Document.Type.PLAIN_TEXT)

    if entity_sentiment:
        entities = _entities_with_sentiment(client, doc)
    else:
        entities = _entities_mention_proxy(client, doc)
    sentiment = with_backoff(client.analyze_sentiment, request={"document": doc}).document_sentiment

    return Extraction(
        ticket_id=ticket_id,
        entities=entities,
        sentiment_score=sentiment.score,
        sentiment_magnitude=sentiment.magnitude,
        units=2 * _units(text),  # entity call + sentiment call, same text
    )


def extract_text(text: str, ticket_id: int = 0, entity_sentiment: bool | None = None) -> Extraction:
    """One-shot extraction for a single piece of text (e.g. the agent tool).

    Builds its own client; for many documents use ``extract_batch``, which
    reuses one client. Defaults the phase to ``CONFIG.nl_entity_sentiment``.
    """
    if entity_sentiment is None:
        entity_sentiment = CONFIG.nl_entity_sentiment
    client, language = make_client(entity_sentiment)
    return extract_one(client, language, ticket_id, text, entity_sentiment)


def extract_batch(
    rows: list[tuple[int, str]],
    max_docs: int,
    entity_sentiment: bool = True,
) -> tuple[list[Extraction], int]:
    """Extract over a sample capped at max_docs (free-tier guardrail).

    Isolates and logs per-document failures rather than failing the batch.
    Returns (extractions, total_units_consumed).
    """
    capped = rows[:max_docs]
    if len(rows) > max_docs:
        log.warning("capping extraction at max_docs=%d (had %d rows)", max_docs, len(rows))

    client, language = make_client(entity_sentiment)
    log.info(
        "extracting with %s (%s)",
        "v1 analyze_entity_sentiment" if entity_sentiment else "v2 analyze_entities",
        "Phase 2" if entity_sentiment else "Phase 1",
    )

    results: list[Extraction] = []
    units = 0
    for i, (ticket_id, text) in enumerate(capped, start=1):
        if not text:
            continue
        try:
            ex = extract_one(client, language, ticket_id, text, entity_sentiment)
            results.append(ex)
            units += ex.units
        except Exception as e:  # per-doc isolation: log and skip
            log.warning("extraction failed for ticket %s: %s", ticket_id, e)
        if i % 25 == 0:
            log.info("extracted %d/%d (%d units so far)", i, len(capped), units)
    return results, units
