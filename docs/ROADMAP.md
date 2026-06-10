# Roadmap and productionization

The prototype is deliberately scoped: a sampled corpus, managed pre-trained
models, batch processing, and a locally-run agent. This document records what a
production version would add and how it would be operated.

## Near-term extensions

- **Graph-primary retrieval.** Build the BigQuery property graph
  (`sql/02_create_graph.sql`), write NL API entities back as `Entity` nodes and
  `MENTIONS` edges, and make the GQL traversal the primary path with the current
  SQL query as fallback. Enables multi-hop queries such as "resolved tickets that
  share tags/entities, plus the users who resolved them."
- **Richer extraction.** Entity-level (aspect) sentiment in addition to document
  sentiment. (A spaCy NER baseline emitting the same schema already ships for a
  side-by-side comparison - see `make baseline`.)
- **Cross-document synthesis.** Given several retrieved resolved tickets, produce
  one "known issue and likely fix" summary that cites every source id, with a
  prompt that refuses when evidence is weak rather than inventing a fix.
- **Agent reasoning.** A `get_resolution` tool that fetches accepted-answer text;
  an explicit clarify path when extracted entities are low-confidence.
- **Cross-session memory.** Persist session turns to **Firestore** (serverless,
  free tier, document model). In-session state uses ADK session state;
  Memorystore (Redis) is heavier than needed, and Agent Engine Memory Bank is the
  managed option once deployed.
- **Evaluation.** ROUGE-L of summaries against accepted answers where present, and
  a full precision/recall/F1 table for extraction against tags.

## Productionization

**Scalability and orchestration.** Replace batch sampling with Pub/Sub-driven
ingestion (new tickets trigger extraction and summarization). Schedule batch
reprocessing and graph refresh with Vertex AI Pipelines. Deploy the agent to
Agent Engine with autoscaling; decompose into a supervisor plus specialist
sub-agents (retriever, summarizer, resolver) via ADK's multi-agent API.

**Security and data privacy.** Least-privilege service accounts per component
(no user credentials in workloads); VPC Service Controls around BigQuery and
Vertex AI; CMEK for BigQuery datasets; a PII redaction step at ingestion.

**Monitoring, logging, error handling.** Cloud Logging and Error Reporting at
every service boundary; Cloud Monitoring dashboards for latency, token cost, and
retrieval quality; alerting on error rate and cost anomalies. Calls already use
bounded retry with backoff and per-document failure isolation.

**Cost management.** Committed-use discounts; Gemini batch mode (lower cost) for
bulk summarization; context caching; model-tier routing (Flash by default, Pro
only for hard reasoning turns).

**CI/CD and reproducibility.** A pipeline of lint -> test -> evaluation gate ->
deploy (GitHub Actions or Cloud Build). Reproducible environments via the locked
requirements and container images; prompt and model versioning with evaluation
gates before any prompt change ships.

## Out of scope

No model fine-tuning (managed pre-trained models only), no streaming ingestion in
the prototype, no full-corpus processing (a sample is intentional), and no custom
UI beyond ADK's local dev interface.
