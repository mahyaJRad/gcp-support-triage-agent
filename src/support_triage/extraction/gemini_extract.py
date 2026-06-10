"""LLM extraction baseline (Gemini Flash) for comparison against the NL API.

A third extractor alongside the managed Cloud Natural Language API
(``nl_api.py``) and the traditional spaCy NER baseline (``baseline_spacy.py``).
``extract_gemini`` emits the SAME entity schema as both
(``name, type, salience, entity_sentiment_*``) so all three can be scored with
the identical entity/tag-overlap metric - see
``support_triage.eval.run.entity_tag_overlap_gemini``.

Unlike spaCy, this costs one Gemini Flash call per document, so callers cap the
document count (``CONFIG.gemini_eval_docs``). Flash only, never Pro, per the
free-tier guardrail. Salience is the model's own importance estimate normalised
to sum to 1; per-entity sentiment is ``None`` (not requested, to keep the call
cheap and the schema parallel to spaCy).
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("support_triage")

# Coarse types aligned with the NL API's set so the three extractors compare
# cleanly; the model is asked to label each entity with one of these.
_ALLOWED_TYPES = {
    "PERSON",
    "LOCATION",
    "ORGANIZATION",
    "EVENT",
    "WORK_OF_ART",
    "CONSUMER_GOOD",
    "DATE",
    "NUMBER",
    "PRICE",
    "OTHER",
}

EXTRACT_PROMPT = (
    "Extract the salient named entities from the following technical support "
    "ticket. Include products, technologies, libraries, services, and APIs - "
    "these are the entities that matter for triage. For each entity return its "
    "surface name, a TYPE from this set "
    "[PERSON, LOCATION, ORGANIZATION, EVENT, WORK_OF_ART, CONSUMER_GOOD, DATE, "
    "NUMBER, PRICE, OTHER] (use OTHER for technologies/APIs/libraries that do not "
    "fit the others), and a salience score in [0,1] for how central it is to the "
    "ticket. Use only entities actually present in the text; do not invent any. "
    "Reply with ONLY a JSON array of objects "
    '[{{"name": "...", "type": "...", "salience": 0.0}}].\n\nTICKET:\n{ticket}\n'
)


def _parse_entities(raw: str) -> list[dict]:
    """Parse the model's JSON reply into the shared entity schema (pure function).

    Tolerates a ```json ... ``` code fence and trailing prose. Each entity is
    normalised to ``{name, type, salience, entity_sentiment_score,
    entity_sentiment_magnitude}``; the type is upper-cased and coerced into the
    allowed set (anything else becomes OTHER); salience is renormalised to sum to
    1 across the document so the output matches the spaCy/NL-API contract.
    Entities are deduped by (name, type) and returned most salient first. A reply
    that is not a JSON array yields an empty list rather than raising.
    """
    text = raw.strip()
    if text.startswith("```"):
        # strip a leading ```json / ``` fence and the trailing ```
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    # be forgiving of trailing prose: grab the first [...] block
    if not text.startswith("["):
        m = re.search(r"\[.*\]", text, re.DOTALL)
        text = m.group(0) if m else text

    try:
        items = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(items, list):
        return []

    # dedupe by (name, type), summing raw salience so repeats stay prominent
    raw_sal: dict[tuple[str, str], float] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()
        if not name:
            continue
        etype = str(it.get("type", "OTHER")).strip().upper()
        if etype not in _ALLOWED_TYPES:
            etype = "OTHER"
        try:
            sal = float(it.get("salience", 0.0))
        except (TypeError, ValueError):
            sal = 0.0
        key = (name, etype)
        raw_sal[key] = raw_sal.get(key, 0.0) + max(sal, 0.0)

    if not raw_sal:
        return []

    # renormalise to sum to 1 (fall back to uniform if the model gave all zeros)
    total = sum(raw_sal.values())
    if total <= 0:
        total = len(raw_sal)
        raw_sal = {k: 1.0 for k in raw_sal}

    out = [
        {
            "name": name,
            "type": etype,
            "salience": round(sal / total, 4),
            "entity_sentiment_score": None,
            "entity_sentiment_magnitude": None,
        }
        for (name, etype), sal in raw_sal.items()
    ]
    return sorted(out, key=lambda d: d["salience"], reverse=True)


def extract_gemini(text: str) -> list[dict]:
    """Extract entities from one ticket with Gemini Flash, in the same shape as the
    NL API and spaCy paths so the three can be scored with the identical metric.

    One Flash call (temperature 0, JSON output). Returns entities most salient
    first; on any model or parse error returns ``[]`` so a batch never crashes.
    """
    if not text:
        return []

    from vertexai.generative_models import GenerationConfig

    from support_triage.gcp import with_backoff
    from support_triage.summarization.gemini import _model

    try:
        resp = with_backoff(
            _model().generate_content,
            EXTRACT_PROMPT.format(ticket=text),
            # gemini-2.5-flash is a thinking model: reasoning shares the output
            # budget, so cap generously to avoid a truncated (invalid) JSON reply.
            generation_config=GenerationConfig(
                temperature=0.0,
                max_output_tokens=1536,
                response_mime_type="application/json",
            ),
        )
        return _parse_entities(resp.text or "")
    except Exception as e:  # best-effort baseline; never break the batch
        log.warning("gemini extraction failed: %s", e)
        return []
