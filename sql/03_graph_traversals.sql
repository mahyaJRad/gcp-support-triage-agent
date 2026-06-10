-- Retrieval: resolved tickets sharing tags/entities with a target ticket.
-- TWO equivalent implementations. The agent tries GQL first, falls back to SQL.

-- ============== (A) GQL graph traversal (preferred; Pre-GA) ==============
-- Shared-tag neighbours that are resolved, ranked by overlap.
SELECT related_id, shared_tags
FROM GRAPH_TABLE (
  `@DATASET.triage_graph`
  MATCH (q1:Question)-[:TAGGED_WITH]->(t:Tag)<-[:TAGGED_WITH]-(q2:Question)
  WHERE q1.id = @ticket_id AND q2.is_resolved AND q1.id <> q2.id
  RETURN q2.id AS related_id, COUNT(t.name) AS shared_tags
  GROUP BY related_id
)
ORDER BY shared_tags DESC
LIMIT 5;

-- ============== (B) SQL fallback (identical semantics, always works) ======
-- Use when BigQuery Graph is unavailable. Tag overlap via self-join on tags.
WITH target AS (
  SELECT SPLIT(tags, '|') AS tags
  FROM `@DATASET.tickets` WHERE id = @ticket_id
),
candidates AS (
  SELECT c.id AS related_id, c.title,
         (SELECT COUNT(*) FROM UNNEST(SPLIT(c.tags,'|')) tg
          WHERE tg IN UNNEST((SELECT tags FROM target))) AS shared_tags
  FROM `@DATASET.tickets` c
  WHERE c.is_resolved AND c.id <> @ticket_id
)
SELECT related_id, title, shared_tags
FROM candidates
WHERE shared_tags > 0
ORDER BY shared_tags DESC
LIMIT 5;
