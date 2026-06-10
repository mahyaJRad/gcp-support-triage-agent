"""Cost-safe ingestion of a sampled Stack Overflow slice into BigQuery.

python -m support_triage.data.ingest [--dry-run]

Two idempotent (CREATE OR REPLACE) steps:
  1. TABLESAMPLE the huge public `posts_questions` table down to a tag-scoped,
     view-ranked slice of only the columns we need (sql/01_sample_corpus.sql).
     This is the ONLY step that scans the big public table, so it is the one
     `--dry-run` estimates.
  2. Strip HTML from each body into `body_clean` (BeautifulSoup) and join it
     back on. BigQuery has no HTML parser, so this runs in Python over the
     already-tiny sampled table.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from support_triage.config import CONFIG

SQL_PATH = Path(__file__).resolve().parents[3] / "sql" / "01_sample_corpus.sql"


def render_sql() -> str:
    """Load 01_sample_corpus.sql and substitute config (tag, row limit, dataset)."""
    sql = SQL_PATH.read_text()
    return (
        sql.replace("@DATASET", CONFIG.dataset)
        .replace("@TAG", CONFIG.sample_tag)
        .replace("@ROWS", str(CONFIG.sample_rows))
        .replace("@PERCENT", str(CONFIG.sample_percent))
    )


def _scan_sql(sql: str) -> str:
    """Isolate the single data-scanning statement from the rendered script.

    The leading `CREATE SCHEMA` (kept so the .sql runs standalone in the console)
    makes the script a multi-statement SCRIPT, which BigQuery dry-runs as 0
    bytes. The `CREATE OR REPLACE TABLE ... AS SELECT` is the only statement that
    touches the public table, so we estimate that one for a real byte figure.
    """
    marker = "CREATE OR REPLACE TABLE"
    _, _, rest = sql.partition(marker)
    return (marker + rest).strip()


def dry_run(sql: str) -> int:
    """Print estimated bytes scanned without running the query. Returns bytes."""
    from google.cloud import bigquery

    from support_triage.gcp import bq_client

    cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = bq_client().query(_scan_sql(sql), job_config=cfg, location=CONFIG.bq_location)
    mb = (job.total_bytes_processed or 0) / 1e6
    print(f"[dry-run] would scan up to ~{mb:.1f} MB (TABLESAMPLE reads less at run time)")
    return job.total_bytes_processed or 0


def _add_body_clean(client) -> None:
    """Add a plain-text `body_clean` column to the sampled tickets table.

    BigQuery cannot run BeautifulSoup, so we pull the (already sampled, small)
    bodies locally, strip HTML, truncate to bound downstream NL API units /
    Gemini tokens, load the result into a staging table, then LEFT JOIN it back
    onto tickets. The raw `body` is preserved. Idempotent: rebuilds the table.
    """
    from google.cloud import bigquery

    from support_triage.data.preprocess import clean_html, truncate
    from support_triage.gcp import with_backoff

    rows = with_backoff(
        client.query,
        f"SELECT id, body FROM `{CONFIG.tickets_table}`",
        location=CONFIG.bq_location,
    ).result()
    cleaned = [{"id": r.id, "body_clean": truncate(clean_html(r.body))} for r in rows]
    if not cleaned:
        print("[ingest] no rows sampled; skipping body_clean enrichment.")
        return

    staging = f"{CONFIG.tickets_table}__clean"
    load_cfg = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("id", "INTEGER"),
            bigquery.SchemaField("body_clean", "STRING"),
        ],
        write_disposition="WRITE_TRUNCATE",
    )
    with_backoff(client.load_table_from_json, cleaned, staging, job_config=load_cfg).result()

    # CREATE OR REPLACE reading from the same table is allowed: BigQuery
    # materializes the SELECT before swapping. Appends body_clean, keeps body.
    with_backoff(
        client.query,
        f"""
        CREATE OR REPLACE TABLE `{CONFIG.tickets_table}` AS
        SELECT t.*, c.body_clean
        FROM `{CONFIG.tickets_table}` t
        LEFT JOIN `{staging}` c USING (id)
        """,
        location=CONFIG.bq_location,
    ).result()
    client.delete_table(staging, not_found_ok=True)


def run() -> None:
    """Create the working dataset if needed, run the sampling query
    (CREATE OR REPLACE), strip HTML into body_clean, and report rows + bytes."""
    from google.cloud import bigquery

    from support_triage.gcp import bq_client, with_backoff

    if not CONFIG.project_id:
        raise SystemExit("GCP_PROJECT_ID is not set; copy .env.example to .env and fill it in.")

    client = bq_client()
    # The working dataset must share the source's location (the public dataset is US).
    ds = bigquery.Dataset(f"{CONFIG.project_id}.{CONFIG.dataset}")
    ds.location = CONFIG.bq_location
    client.create_dataset(ds, exists_ok=True)

    sql = render_sql()
    print(
        f"[ingest] sampling up to {CONFIG.sample_rows} '{CONFIG.sample_tag}' "
        f"questions -> {CONFIG.tickets_table}"
    )
    job = with_backoff(client.query, sql, location=CONFIG.bq_location)
    job.result()
    scanned_mb = (job.total_bytes_processed or 0) / 1e6

    _add_body_clean(client)

    table = client.get_table(CONFIG.tickets_table)
    print(f"[ingest] wrote {table.num_rows} rows ({scanned_mb:.1f} MB scanned).")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    sql = render_sql()
    if args.dry_run:
        print(sql)
        dry_run(sql)
    else:
        run()
