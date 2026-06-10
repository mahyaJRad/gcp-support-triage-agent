"""Create the BigQuery property graph from node/edge tables."""

from __future__ import annotations

from pathlib import Path

DDL_PATH = Path(__file__).resolve().parents[3] / "sql" / "02_create_graph.sql"


def build() -> None:
    """Derive the node/edge tables and run the CREATE PROPERTY GRAPH DDL.

    BigQuery Graph is Pre-GA; retrieval falls back to SQL if the graph is
    unavailable (see docs/adr/0003-graph-vs-vector-retrieval.md).
    """
    raise NotImplementedError


if __name__ == "__main__":
    build()
