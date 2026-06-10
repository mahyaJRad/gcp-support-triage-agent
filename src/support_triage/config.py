"""Central config, loaded from environment (.env). No secrets hard-coded."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    project_id: str = os.environ.get("GCP_PROJECT_ID", "")
    region: str = os.environ.get("GCP_REGION", "us-central1")
    # BigQuery
    # Dataset/query location. MUST match the source: bigquery-public-data lives in
    # the `US` multi-region, so the working dataset and all jobs must run in `US`
    # (a regional location like us-central1 would raise a cross-location error).
    bq_location: str = os.environ.get("BQ_LOCATION", "US")
    source_table: str = os.environ.get("BQ_SOURCE_TABLE", "bigquery-public-data.stackoverflow")
    dataset: str = os.environ.get("BQ_DATASET", "support_triage")
    sample_tag: str = os.environ.get("BQ_SAMPLE_TAG", "google-cloud-platform")
    sample_rows: int = int(os.environ.get("BQ_SAMPLE_ROWS", "1000"))
    # TABLESAMPLE fraction of posts_questions to scan. ~5% keeps the ingest scan
    # under 2 GB while still returning plenty of tag-matched rows.
    sample_percent: int = int(os.environ.get("BQ_SAMPLE_PERCENT", "5"))
    graph_name: str = os.environ.get("BQ_GRAPH_NAME", "triage_graph")
    # cost guardrail: never extract/summarize more than this many docs at once
    max_docs: int = int(os.environ.get("MAX_DOCS", "300"))
    # NL API: chars per billed unit, and the truncation cap (1 unit ~= 1000 chars)
    nl_unit_chars: int = int(os.environ.get("NL_UNIT_CHARS", "1000"))
    # Phase 2: use v1 analyze_entity_sentiment (real salience + per-entity
    # sentiment). Phase 1 (False) uses v2 analyze_entities with a mention-count
    # salience proxy and no per-entity sentiment.
    nl_entity_sentiment: bool = os.environ.get("NL_ENTITY_SENTIMENT", "true").lower() == "true"
    # Vertex / Gemini
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    vertex_location: str = os.environ.get("VERTEX_LOCATION", "us-central1")
    # Firestore (optional)
    firestore_collection: str = os.environ.get("FIRESTORE_COLLECTION", "triage_sessions")

    @property
    def tickets_table(self) -> str:
        return f"{self.project_id}.{self.dataset}.tickets"

    @property
    def entities_table(self) -> str:
        return f"{self.project_id}.{self.dataset}.entities"

    @property
    def summaries_table(self) -> str:
        return f"{self.project_id}.{self.dataset}.summaries"


CONFIG = Config()
