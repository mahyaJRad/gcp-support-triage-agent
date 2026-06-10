# Roadmap and productionization

The prototype is deliberately scoped: a sampled corpus, managed pre-trained
models, batch processing, and a locally-run agent. This document records what a
production version would add and how it would be operated.

## Near-term extensions

- **Graph-primary retrieval (designed, not yet built).** Today retrieval is a
  single-hop lexical tag-overlap SQL query; the property graph is
  *scaffolded* (DDL `sql/02_create_graph.sql`, a sample GQL traversal, and a
  `use_graph` code path) but **`graph/build.py` is a stub and the agent never calls
  the graph** - so nothing is built or wired today. To finish it: build the
  node/edge tables from `tickets`+`entities`, write NL API entities back as `Entity`
  nodes and `MENTIONS` edges, run `CREATE PROPERTY GRAPH`, and make the GQL
  traversal the primary path with the current SQL query as automatic fallback.
  *Why it's worth it:* a single-hop overlap does not justify a graph (SQL does it
  well); the graph earns its place on **multi-hop** queries SQL is awkward at -
  combined tag+entity relevance, **entity-bridge** precedents (share an entity but
  no tag, invisible to tag overlap), and **expert routing** (ticket -> accepted
  answer -> answerer -> their other resolved tickets). Prove it with **recall@k /
  MRR vs the SQL baseline** rather than asserting it (ADR 0003).
- **Cross-document synthesis.** Given several retrieved resolved tickets, produce
  one "known issue and likely fix" summary that cites every source id, with a
  prompt that refuses when evidence is weak rather than inventing a fix.
- **`get_resolution` + true resolution summaries.** Re-ingest accepted-answer text
  (join `posts_answers` on `accepted_answer_id`), add a tool to fetch it, and
  summarize the *resolution* rather than the question - closing today's "resolution
  unknown" gap and unlocking the deferred **ROUGE-L vs. accepted answers** metric.
- **Hybrid semantic retrieval.** Vertex AI embeddings + Vector Search alongside the
  lexical/graph retrieval, ranked together, for fuzzy prose phrasing.
- **Frontier-model routing.** Tiered model selection - Flash for bulk/simple steps,
  a frontier model (Gemini Pro / frontier tier) for complex multi-step agent
  reasoning turns - instead of Flash everywhere (ADR 0004).
- **Multi-agent decomposition.** A supervisor agent over specialist sub-agents
  (retriever, summarizer, resolver) via ADK's multi-agent API.
- **Confidence-aware clarify / abstain.** An explicit low-confidence path that asks
  one targeted clarifying question or abstains, driven by extraction salience and
  retrieval score.
- **Cross-session memory.** Persist session turns to **Firestore** (serverless,
  free tier, document model). In-session state uses ADK session state;
  Memorystore (Redis) is heavier than needed, and Agent Engine Memory Bank is the
  managed option once deployed.
- **Evaluation.** Retrieval-quality metrics (recall@k / MRR) as a CI gate once the
  graph lands; ROUGE-L of summaries against accepted answers where present; the
  full precision/recall/F1 table for extraction against tags (shipped).

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
