"""Entry point: summarize the sample and write CONFIG.summaries_table."""

from __future__ import annotations

import argparse
import logging

from support_triage.config import CONFIG
from support_triage.data.preprocess import clean_html, truncate
from support_triage.summarization.gemini import summarize

log = logging.getLogger("support_triage")


def run(limit: int | None = None) -> None:
    """Summarize a sample of tickets and write CONFIG.summaries_table.

    Pass ``limit`` (e.g. 20) for a cheap sanity check before the full sample.
    """
    import pandas as pd
    from google.cloud import bigquery

    from support_triage.gcp import bq_client

    n = limit or CONFIG.max_docs
    client = bq_client()

    rows = client.query(
        f"""
        SELECT id, title, body
        FROM `{CONFIG.tickets_table}`
        ORDER BY view_count DESC
        LIMIT {n}
        """,
        location=CONFIG.bq_location,
    ).result()

    rows = list(rows)
    log.info("summarizing %d tickets with %s", len(rows), CONFIG.gemini_model)

    records = []
    for i, r in enumerate(rows, start=1):
        text = truncate(f"{r['title']}. {clean_html(r['body'])}")
        try:
            summary = summarize(text)
            if not summary:  # safety-blocked or empty completion
                log.warning("empty summary for ticket %s; skipping", r["id"])
                continue
            records.append(
                {
                    "ticket_id": r["id"],
                    "title": r["title"],
                    "summary": summary,
                    "model": CONFIG.gemini_model,  # provenance for the report / eval
                }
            )
        except Exception as e:  # isolate per-doc failures
            log.warning("summarization failed for ticket %s: %s", r["id"], e)
        if i % 25 == 0:
            log.info("summarized %d/%d", i, len(rows))

    df = pd.DataFrame.from_records(records)
    job = client.load_table_from_dataframe(
        df,
        CONFIG.summaries_table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
        location=CONFIG.bq_location,
    )
    job.result()
    print(
        f"[summarize] wrote {len(df)} summaries -> {CONFIG.summaries_table} "
        f"(model={CONFIG.gemini_model})"
    )

    print("\n[summarize] example summaries:")
    for rec in records[:3]:
        print(f"\n  ticket {rec['ticket_id']} - {rec['title']}\n    {rec['summary']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None, help="sanity-check on N rows (e.g. 20)")
    args = p.parse_args()
    run(limit=args.limit)
