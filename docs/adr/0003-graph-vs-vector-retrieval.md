# ADR 0003 - Retrieval via BigQuery (SQL now, GQL property graph later)

## Status
Accepted

## Context
The agent must find historically similar resolved tickets. Options: flat SQL
joins, vector similarity, or a property graph.

## Decision
Retrieve resolved tickets by tag/entity overlap in BigQuery. Phase 1 uses a SQL
query (guaranteed to work). The same relationship is expressible as a BigQuery
**property graph** with GQL traversal, which the retrieval tool prefers when the
graph has been built - the natural path for multi-hop queries.

## Alternatives considered
- **Flat SQL joins only:** fine for one hop; "tickets sharing tags and entities,
  plus the expert who resolved them" is multi-hop and becomes unwieldy in SQL.
- **Vector search (Vertex AI Vector Search):** strong for fuzzy semantic match,
  but adds an embedding pipeline and index cost and does not capture explicit
  user/tag/answer relationships. A candidate for a hybrid approach later.

## Consequences
- (+) Runs on standard BigQuery, no new service, stays in the free query tier.
- (+) Relationship traversal is first-class and readable in GQL
  (`MATCH ... -[]-> ...`).
- (+) Clean seam for a future hybrid (graph edges plus vector similarity).
- (-) BigQuery Graph is Pre-GA. Mitigation: the identical traversal exists as SQL
  in `sql/03_graph_traversals.sql`, and the tool falls back to it automatically.
