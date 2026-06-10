-- Cost-safe corpus sampling. Placeholders (@DATASET, @TAG, @ROWS, @PERCENT) are
-- substituted by support_triage.data.ingest. Always dry-run first.
--
-- posts_questions is large and not clustered on tags, so a plain scan of the
-- referenced columns (notably `body`) reads tens of GB. TABLESAMPLE SYSTEM reads
-- only a random fraction of the table's blocks, bounding bytes scanned to roughly
-- that fraction while still yielding ample tag-matched rows for a prototype.
CREATE SCHEMA IF NOT EXISTS `@DATASET`;

CREATE OR REPLACE TABLE `@DATASET.tickets` AS
SELECT
  id,
  title,
  body,                                   -- raw HTML; cleaned in preprocess
  tags,                                   -- '|'-separated; gold standard for eval
  answer_count,
  accepted_answer_id,
  (accepted_answer_id IS NOT NULL) AS is_resolved,
  score,
  view_count,
  owner_user_id,
  creation_date
FROM `bigquery-public-data.stackoverflow.posts_questions` TABLESAMPLE SYSTEM (@PERCENT PERCENT)
WHERE '@TAG' IN UNNEST(SPLIT(tags, '|'))
  AND body IS NOT NULL
ORDER BY view_count DESC
LIMIT @ROWS;
