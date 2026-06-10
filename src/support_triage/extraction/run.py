"""Entry point: extract over the sample and write CONFIG.entities_table.

Output is long-format - one row per (ticket_id, entity) plus the document
sentiment denormalised onto each row - which feeds both the eval (entity<->tag
overlap) and the Phase-2 graph ENTITY nodes / MENTIONS edges.
"""

from __future__ import annotations

import logging

from support_triage.config import CONFIG
from support_triage.data.preprocess import clean_html, truncate
from support_triage.extraction.nl_api import extract_batch

log = logging.getLogger("support_triage")


def run() -> None:
    import pandas as pd
    from google.cloud import bigquery

    from support_triage.gcp import bq_client

    client = bq_client()

    # Pull a capped sample of the most-viewed tickets; clean HTML + truncate to
    # control NL API units (1 unit ~= 1000 chars).
    rows = client.query(
        f"""
        SELECT id, title, body
        FROM `{CONFIG.tickets_table}`
        ORDER BY view_count DESC
        LIMIT {CONFIG.max_docs}
        """,
        location=CONFIG.bq_location,
    ).result()

    docs: list[tuple[int, str]] = []
    for r in rows:
        text = truncate(f"{r['title']}. {clean_html(r['body'])}")
        docs.append((r["id"], text))

    log.info("extracting entities + sentiment for %d tickets", len(docs))
    extractions, units = extract_batch(
        docs, max_docs=CONFIG.max_docs, entity_sentiment=CONFIG.nl_entity_sentiment
    )

    records = []
    for ex in extractions:
        if not ex.entities:
            # keep a row so sentiment-only tickets still appear
            records.append(
                {
                    "ticket_id": ex.ticket_id,
                    "entity_name": None,
                    "entity_type": None,
                    "salience": None,
                    "entity_sentiment_score": None,
                    "entity_sentiment_magnitude": None,
                    "sentiment_score": ex.sentiment_score,
                    "sentiment_magnitude": ex.sentiment_magnitude,
                }
            )
        for ent in ex.entities:
            records.append(
                {
                    "ticket_id": ex.ticket_id,
                    "entity_name": ent["name"],
                    "entity_type": ent["type"],
                    "salience": ent["salience"],
                    "entity_sentiment_score": ent["entity_sentiment_score"],
                    "entity_sentiment_magnitude": ent["entity_sentiment_magnitude"],
                    "sentiment_score": ex.sentiment_score,
                    "sentiment_magnitude": ex.sentiment_magnitude,
                }
            )

    df = pd.DataFrame.from_records(records)
    # WRITE_TRUNCATE replaces data *and* schema (CREATE OR REPLACE semantics),
    # so the Phase-2 entity-sentiment columns are picked up automatically.
    job = client.load_table_from_dataframe(
        df,
        CONFIG.entities_table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
        location=CONFIG.bq_location,
    )
    job.result()

    phase = "Phase 2 (entity-sentiment)" if CONFIG.nl_entity_sentiment else "Phase 1 (entities)"
    print(
        f"[extract] {phase}: wrote {len(df)} entity rows for {len(extractions)} tickets "
        f"-> {CONFIG.entities_table}"
    )
    print(f"[extract] NL units consumed: {units} (free tier: 5,000/month)")

    # A few example extractions for the report / sanity check.
    print("\n[extract] example extractions:")
    for ex in extractions[:3]:
        parts = []
        for e in ex.entities[:5]:
            tag = f"{e['name']}({e['type']},sal={e['salience']}"
            if e["entity_sentiment_score"] is not None:
                tag += f",sent={e['entity_sentiment_score']}"
            parts.append(tag + ")")
        ents = ", ".join(parts)
        print(f"  ticket {ex.ticket_id} | doc_sentiment={ex.sentiment_score:+.2f} | {ents}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
