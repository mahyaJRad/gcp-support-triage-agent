# ADR 0003 - Retrieval via BigQuery (SQL implemented; GQL property graph deferred)

## Status
Accepted - **SQL implemented; property graph deferred (designed, not built)**.

## Context
The agent must find historically similar resolved tickets. Options: flat SQL
joins, vector similarity, or a property graph.

## Decision
Retrieve resolved tickets by tag overlap in BigQuery. **What runs today** is
a SQL query (`graph/queries.py:find_related_by_text`) - guaranteed to work, free,
and unit-tested. The same relationship is expressible as a BigQuery **property
graph** with GQL traversal, which is the natural path for multi-hop queries.

**Current state (be precise):** the property graph is **scaffolded but not built or
wired**. The DDL (`sql/02_create_graph.sql`), a sample GQL traversal
(`sql/03_graph_traversals.sql`), and a `use_graph` code path
(`graph/queries.py:_graph_by_id`) all exist, but `graph/build.py` is a stub
(`raise NotImplementedError`) so no graph object is created, and the agent's
`find_related_tickets` tool only ever calls the SQL path. No graph is built and
nothing uses it today.

## Potential improvement - how it would be explored, and why
A single-hop tag overlap does **not** justify a graph - SQL does it well. The graph
earns its place only on **multi-hop** questions that are awkward as nested SQL
self-joins:
- **(i) Combined tag + entity relevance** - rank precedents by shared tags *and*
  shared extracted entities in one traversal, weighting specific entity matches.
- **(ii) Entity-bridge precedents** - resolved tickets that share an *entity* but
  **no tag** with the incoming ticket; invisible to tag-overlap SQL, yet often the
  most useful non-obvious precedents.
- **(iii) Expert routing** - ticket -> accepted answer -> answerer -> that expert's
  other resolved tickets (a genuine 2-hop traversal; needs the accepted-answer
  author, i.e. the answer re-ingest noted in `docs/ROADMAP.md`).

*How to explore:* derive node/edge tables from `tickets`+`entities`, run
`CREATE PROPERTY GRAPH`, write the multi-hop GQL traversals, wire the agent's
retrieval to the graph as the **primary path with the current SQL as an automatic
fallback** (BigQuery Graph is Pre-GA), and **measure** recall@k / MRR vs the SQL
baseline plus the count of entity-bridge precedents SQL never surfaces - so the
graph is justified with numbers, not asserted.

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
- (-) BigQuery Graph is Pre-GA - a reason it is deferred rather than relied on.
  Mitigation by design: the identical traversal exists as SQL in
  `sql/03_graph_traversals.sql` (the path the agent uses today), and the
  `use_graph` code path is written to fall back to SQL automatically once the graph
  is actually built.
