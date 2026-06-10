"""Retrieval queries over the ticket corpus.

The default path is a BigQuery SQL tag-overlap query, which always works. When
``use_graph=True`` and the property graph has been built, the GQL traversal is
used instead, falling back to SQL on any error. The SQL mirrors section (B) of
sql/03_graph_traversals.sql.
"""

from __future__ import annotations

import logging
import re

from support_triage.config import CONFIG

log = logging.getLogger("support_triage")


def _url(ticket_id: int) -> str:
    return f"https://stackoverflow.com/q/{ticket_id}"


def _terms(text: str) -> list[str]:
    """Lowercased alphanumeric tokens (len>=2), deduped - used for tag overlap."""
    seen, out = set(), []
    for tok in re.split(r"[^a-z0-9+#.\-]+", (text or "").lower()):
        if len(tok) >= 2 and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _sql_by_id(ticket_id: int, top_k: int) -> list[dict]:
    from google.cloud import bigquery

    from support_triage.gcp import bq_client

    sql = f"""
    WITH target AS (
      SELECT SPLIT(tags, '|') AS tags FROM `{CONFIG.tickets_table}` WHERE id = @ticket_id
    )
    SELECT * FROM (
      SELECT c.id AS id, c.title AS title, c.score AS score,
             (SELECT COUNT(*) FROM UNNEST(SPLIT(c.tags, '|')) tg
              WHERE tg IN UNNEST((SELECT tags FROM target))) AS shared_tags
      FROM `{CONFIG.tickets_table}` c
      WHERE c.is_resolved AND c.id <> @ticket_id
    )
    WHERE shared_tags > 0
    ORDER BY shared_tags DESC, score DESC
    LIMIT @top_k
    """
    cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("ticket_id", "INT64", ticket_id),
            bigquery.ScalarQueryParameter("top_k", "INT64", top_k),
        ]
    )
    rows = bq_client().query(sql, job_config=cfg, location=CONFIG.bq_location).result()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "shared_tags": r["shared_tags"],
            "score": r["score"],
            "url": _url(r["id"]),
        }
        for r in rows
    ]


def _graph_by_id(ticket_id: int, top_k: int) -> list[dict]:
    """GQL traversal over the property graph (Pre-GA). Mirrors sql/03 section (A)."""
    from google.cloud import bigquery

    from support_triage.gcp import bq_client

    sql = f"""
    SELECT gt.related_id AS id, t.title AS title, t.score AS score, gt.shared_tags AS shared_tags
    FROM GRAPH_TABLE (
      `{CONFIG.project_id}.{CONFIG.dataset}.{CONFIG.graph_name}`
      MATCH (q1:Question)-[:TAGGED_WITH]->(tg:Tag)<-[:TAGGED_WITH]-(q2:Question)
      WHERE q1.id = @ticket_id AND q2.is_resolved AND q1.id <> q2.id
      RETURN q2.id AS related_id, COUNT(tg.name) AS shared_tags
      GROUP BY related_id
    ) gt
    JOIN `{CONFIG.tickets_table}` t ON t.id = gt.related_id
    ORDER BY gt.shared_tags DESC, t.score DESC
    LIMIT @top_k
    """
    cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("ticket_id", "INT64", ticket_id),
            bigquery.ScalarQueryParameter("top_k", "INT64", top_k),
        ]
    )
    rows = bq_client().query(sql, job_config=cfg, location=CONFIG.bq_location).result()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "shared_tags": r["shared_tags"],
            "score": r["score"],
            "url": _url(r["id"]),
        }
        for r in rows
    ]


def find_related_tickets(ticket_id: int, top_k: int = 5, use_graph: bool = False) -> list[dict]:
    """Return resolved tickets sharing tags with `ticket_id`.

    Phase 1: SQL self-join (guaranteed). Set ``use_graph=True`` once the property
    graph is built to use the GQL traversal; on any graph error it falls back to
    SQL. Returns [{id, title, shared_tags, score, url}].
    """
    if use_graph:
        try:
            return _graph_by_id(ticket_id, top_k)
        except Exception as e:  # Pre-GA graph or not built -> SQL fallback
            log.warning("graph traversal unavailable (%s); falling back to SQL", e)
    return _sql_by_id(ticket_id, top_k)


def find_related_by_text(ticket_text: str, top_k: int = 5) -> list[dict]:
    """Retrieve resolved tickets whose tags overlap the free-text query.

    Unlike `find_related_tickets` (which needs an in-corpus id), this accepts an
    arbitrary incoming ticket - what the agent actually has. Ranks resolved
    tickets by how many of their tags appear as terms in the text.
    Returns [{id, title, shared_tags, score, url}].
    """
    from google.cloud import bigquery

    from support_triage.gcp import bq_client

    terms = _terms(ticket_text)
    if not terms:
        return []

    sql = f"""
    SELECT * FROM (
      SELECT id, title, score,
             (SELECT COUNT(*) FROM UNNEST(SPLIT(LOWER(tags), '|')) tg
              WHERE tg IN UNNEST(@terms)) AS shared_tags
      FROM `{CONFIG.tickets_table}`
      WHERE is_resolved
    )
    WHERE shared_tags > 0
    ORDER BY shared_tags DESC, score DESC
    LIMIT @top_k
    """
    cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("terms", "STRING", terms),
            bigquery.ScalarQueryParameter("top_k", "INT64", top_k),
        ]
    )
    rows = bq_client().query(sql, job_config=cfg, location=CONFIG.bq_location).result()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "shared_tags": r["shared_tags"],
            "score": r["score"],
            "url": _url(r["id"]),
        }
        for r in rows
    ]
