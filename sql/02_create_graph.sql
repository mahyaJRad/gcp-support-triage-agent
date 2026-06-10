-- Property graph over the sampled corpus. BigQuery Graph is Pre-GA (preview).
-- Assumes node/edge tables built from tickets + entities (see graph/build.py):
--   nodes: questions(id,...), users(id,...), tags(name), entities(name,type)
--   edges: q_tag(question_id,tag_name), q_entity(question_id,entity_name),
--          q_user(question_id,user_id)
CREATE OR REPLACE PROPERTY GRAPH `@DATASET.triage_graph`
NODE TABLES (
  `@DATASET.questions` KEY (id)
      LABEL Question PROPERTIES (id, title, is_resolved, sentiment),
  `@DATASET.users` KEY (id)
      LABEL User PROPERTIES (id, reputation),
  `@DATASET.tags` KEY (name)
      LABEL Tag PROPERTIES (name),
  `@DATASET.entities_nodes` KEY (name)
      LABEL Entity PROPERTIES (name, type)
)
EDGE TABLES (
  `@DATASET.q_tag`
      SOURCE KEY (question_id) REFERENCES `@DATASET.questions` (id)
      DESTINATION KEY (tag_name) REFERENCES `@DATASET.tags` (name)
      LABEL TAGGED_WITH,
  `@DATASET.q_entity`
      SOURCE KEY (question_id) REFERENCES `@DATASET.questions` (id)
      DESTINATION KEY (entity_name) REFERENCES `@DATASET.entities_nodes` (name)
      LABEL MENTIONS,
  `@DATASET.q_user`
      SOURCE KEY (question_id) REFERENCES `@DATASET.questions` (id)
      DESTINATION KEY (user_id) REFERENCES `@DATASET.users` (id)
      LABEL ASKED_BY
);
