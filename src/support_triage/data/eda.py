"""Minimal EDA over the tickets table. Run: python -m support_triage.data.eda"""

from __future__ import annotations

from support_triage.config import CONFIG


def run() -> None:
    """Print count, body-length stats, top tags, resolved rate, time range.

    Keep it tiny (this is the script form; richer charts live in notebooks/01_eda.ipynb).
    """
    from google.cloud import bigquery

    from support_triage.gcp import bq_client

    client = bq_client()
    t = CONFIG.tickets_table

    summary = list(
        client.query(
            f"""
            SELECT
              COUNT(*)                                    AS n,
              ROUND(AVG(LENGTH(body)))                    AS avg_body_chars,
              MIN(LENGTH(body))                           AS min_body_chars,
              APPROX_QUANTILES(LENGTH(body), 2)[OFFSET(1)] AS median_body_chars,
              MAX(LENGTH(body))                           AS max_body_chars,
              ROUND(100 * COUNTIF(is_resolved) / COUNT(*), 1) AS resolved_pct,
              MIN(creation_date)                          AS earliest,
              MAX(creation_date)                          AS latest
            FROM `{t}`
            """,
            location=CONFIG.bq_location,
        ).result()
    )[0]

    print(f"=== EDA: {t} ===")
    print(f"tickets              : {summary['n']}")
    print(
        f"body length (chars)  : median {summary['median_body_chars']}, "
        f"avg {summary['avg_body_chars']}, "
        f"min {summary['min_body_chars']}, max {summary['max_body_chars']}"
    )
    print(f"resolved (accepted)  : {summary['resolved_pct']}%")
    print(f"date range           : {summary['earliest']:%Y-%m-%d} -> {summary['latest']:%Y-%m-%d}")

    # Exclude the sampling tag (on every row) to show the GCP products that dominate.
    print(f"\ntop 15 co-occurring tags (excl. {CONFIG.sample_tag}):")
    top_tags = client.query(
        f"""
        SELECT tag, COUNT(*) AS c, ROUND(100 * COUNTIF(is_resolved) / COUNT(*), 1) AS resolved_pct
        FROM `{t}`, UNNEST(SPLIT(tags, '|')) AS tag
        WHERE tag != @sample_tag
        GROUP BY tag
        ORDER BY c DESC
        LIMIT 15
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("sample_tag", "STRING", CONFIG.sample_tag)
            ]
        ),
        location=CONFIG.bq_location,
    ).result()
    for row in top_tags:
        print(f"  {row['tag']:<30} {row['c']:>5}  ({row['resolved_pct']}% resolved)")


if __name__ == "__main__":
    run()
