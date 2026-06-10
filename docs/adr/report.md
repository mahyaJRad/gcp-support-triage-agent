  Architecture & Agent Design Report

  Intelligent Data Extraction & Summarization with Agentic Workflows on GCP

  Prototype: Support-Triage Agent, Date: 2026-06-09 

  ---
  1. Executive Summary

  This prototype is a Support-Triage Agent: given an incoming technical support ticket, it (1) extracts the core issue, entities and sentiment, (2) retrieves historically similar resolved tickets,
  and (3) summarizes the likely fix into a grounded brief that cites its sources. When no precedent exists, it says so and recommends escalation rather than inventing an answer.

  The system is built GCP-native end to end, BigQuery (corpus + relationship retrieval), Cloud Natural Language API (extraction), Vertex AI / Gemini Flash (summarization) — and orchestrated as
  modular tools behind a Google ADK agent. The architectural differentiator is retrieval modeled as a BigQuery property graph (GQL traversal) with a guaranteed SQL fallback, which generalizes
  naturally to multi-hop "who resolved similar issues" queries without standing up a separate vector database.

  Every artifact (sampled corpus, entities, summaries, graph) is regenerable from a single make target or slash command, and every component choice is recorded in an Architecture Decision Record
  (ADR).

  Scope discipline: the work is organized in three phases. Phase 1 (working) and Phase 2 (improved) are implemented; Phase 3 (full product) — managed Agent Engine deployment, cross-session memory,
  vector hybrid retrieval — is documented as roadmap only. This keeps the prototype honest about what runs today versus what productionization would add (§9).

  ---
  2. Scenario & Agent Goal

  Business problem. A support team answers variations of the same technical questions repeatedly, and the knowledge of how each was resolved is scattered across thousands of past tickets.
  First-response time suffers and answers drift in quality.

  Agent goal. Answer "What is the likely fix for this ticket?" by grounding the response in prior resolved tickets — shortening first-response time and keeping answers consistent and citable.
  Explicitly escalate when there is no precedent, so the agent never fabricates a fix.

  Why this dataset (ADR 0001). We model tickets on the public Stack Overflow dataset (bigquery-public-data.stackoverflow), scoped to the google-cloud-platform tag domain. It is already hosted in
  BigQuery (zero-egress, serverless), and its tags are a free gold standard for evaluating extraction. Its structure (questions, answers, tags, users) justifies relationship-based retrieval, and
  "an accepted answer to a resolved question" is a clean proxy for "a known fix."

  ---
  3. Task 1 — Data Preparation & Exploration

  Storage (GCP-native). A tag-scoped, cost-bounded sample of the public dataset is copied into a working BigQuery dataset (support_triage). Sampling uses TABLESAMPLE (~5%) plus a tag filter and a
  row cap, with column projection — keeping the ingest scan in the low-MB range (ADR 0004).

  Working corpus (actuals in this run):

  ┌───────────────────┬───────┬───────────────────────────────────────────────────────────┐
  │       Table       │ Rows  │                           Notes                           │
  ├───────────────────┼───────┼───────────────────────────────────────────────────────────┤
  │ tickets           │ 2,894 │ sampled questions; is_resolved = has an accepted answer   │
  ├───────────────────┼───────┼───────────────────────────────────────────────────────────┤
  │ of which resolved │ 1,248 │ the retrieval candidate pool                              │
  ├───────────────────┼───────┼───────────────────────────────────────────────────────────┤
  │ entities          │ 7,911 │ NL API entities + sentiment, one row per (ticket, entity) │
  ├───────────────────┼───────┼───────────────────────────────────────────────────────────┤
  │ summaries         │ 300   │ Gemini Flash briefs (provenance: model column)            │
  └───────────────────┴───────┴───────────────────────────────────────────────────────────┘

  Preprocessing. HTML stripping (clean_html), whitespace/code-fence normalization to body_clean, and length truncation (truncate) so each document stays within one NL API billed unit (~1,000 chars)
  — both a quality and a cost control.

  EDA. make eda profiles tag frequency, resolved-rate, body length, and score distributions. Representative findings: the corpus is dominated by google-cloud-functions, google-cloud-storage,
  google-bigquery, kubernetes/google-kubernetes-engine, google-app-engine — confirming enough intra-tag overlap to make tag-based retrieval meaningful, and ~43% resolved (1,248 / 2,894), a healthy
  precedent pool.

  ---
  4. Task 2 — Information Extraction & Summarization

  4.1 Extraction — Cloud Natural Language API (ADR 0002)

  We use the Cloud Natural Language API for entity analysis and document sentiment rather than an LLM-extraction path, because it is managed, deterministic, snapshot-testable, and free within the
  standing 5,000-units/month allowance. The entities table captures per-entity salience, entity_sentiment_score/magnitude, and document-level sentiment_score/magnitude.

  - Phase 1 used v2 analyze_entities with a mention-frequency salience proxy (v2 dropped the salience field).
  - Phase 2 (current) uses v1 analyze_entity_sentiment for real salience + per-entity sentiment — surfacing not just what a ticket is about but which entity the user is frustrated with.
  - An optional spaCy baseline (extraction/baseline_spacy.py) is included for the assignment's "compare with traditional NLP" prompt: it offers fast, offline NER but no managed sentiment and weaker
  domain typing — illustrating why the managed API wins for this use case.

  4.2 Summarization — Gemini Flash on Vertex AI (ADR 0004)

  Summaries are generated by Gemini 2.5 Flash via Vertex AI (vertexai.generative_models SDK). Flash, never Pro, for batch work — adequate quality at a fraction of the cost. Key design choices:

  - Grounded prompt: "summarize ONLY from the provided ticket; if the resolution is unknown, say so; do not invent fixes." Output is one ~60-word paragraph at temperature=0.2 for consistency.
  - Source id stored alongside each summary, so the agent can cite it and the evaluator can check grounding.
  - Thinking-token robustness: gemini-2.5-flash is a thinking model whose reasoning tokens draw from the output budget; too small a cap truncates summaries mid-sentence. We set a generous
  max_output_tokens and add a _trim_to_last_sentence safety net so a rare reasoning spike never persists a partial clause.

  Sample output (grounded; note the explicit "resolution is unknown"):

  ▎ [47999146] How do I authenticate GKE to my third-party private docker registry? — "The user wants to know how to authenticate their GKE Kubernetes cluster to a third-party private Docker
  ▎ registry, not GCP's, to pull images for deploying pods… The resolution for this issue is currently unknown."

  ---
  5. Evaluation (Results)

  Stack Overflow tags provide a free gold standard, enabling one genuine quantitative metric plus a qualitative spot-check (make eval).

  5.1 Quantitative — extracted entities vs. tags (n = 300)

  ┌───────────┬───────┐
  │  Metric   │ Value │
  ├───────────┼───────┤
  │ Precision │ 0.174 │
  ├───────────┼───────┤
  │ Recall    │ 0.778 │
  ├───────────┼───────┤
  │ F1        │ 0.285 │
  └───────────┴───────┘

  Reading the numbers. Match = token-set overlap between an entity and a tag (so "Google Cloud" matches google-cloud-platform). The high-recall / low-precision shape is exactly what we expect and
  is a feature of the measurement, not a defect of extraction: the NL API surfaces a broad set of real-world entities (products, people, generic nouns), while tags are a small, curated set — so
  most tags are covered (recall 0.78) but many legitimately-extracted entities have no corresponding tag (precision 0.17). The metric is summary-independent and stable across runs, making it a
  reliable regression signal.

  5.2 Qualitative — summary faithfulness & usefulness (Gemini-Flash LLM judge)

  A 5-ticket spot-check scores each summary 1–5 for faithfulness (every claim supported by the ticket; no invented fixes) and usefulness (would it help an engineer triage). Current run: mean 5.0/5
  faithfulness, 5.0/5 usefulness.

  ┌──────────┬──────────┬────────┬────────────────────────────────────────────────────────────────┐
  │  Ticket  │ Faithful │ Useful │                           Judge note                           │
  ├──────────┼──────────┼────────┼────────────────────────────────────────────────────────────────┤
  │ 47993099 │    5     │   5    │ Accurately captures problem, method, error, user's confusion   │
  ├──────────┼──────────┼────────┼────────────────────────────────────────────────────────────────┤
  │ 47999146 │    5     │   5    │ Concise; captures all key details; no invented facts           │
  ├──────────┼──────────┼────────┼────────────────────────────────────────────────────────────────┤
  │ 48014237 │    5     │   5    │ Captures problem, tech, user's question; no invented facts     │
  ├──────────┼──────────┼────────┼────────────────────────────────────────────────────────────────┤
  │ 48015085 │    5     │   5    │ Captures problem, platform, likely cause; excellent for triage │
  ├──────────┼──────────┼────────┼────────────────────────────────────────────────────────────────┤
  │ 48033628 │    5     │   5    │ Perfectly faithful; all key details for quick triage           │
  └──────────┴──────────┴────────┴────────────────────────────────────────────────────────────────┘

  Honest caveat. This is a Gemini-judging-Gemini check, so the uniform top score reflects both genuinely faithful summaries and known self-judge leniency. It is a sanity check, not a hard
  benchmark; §9 describes how a production eval would add human-rated anchors and an independent judge model.

  5.3 Phase-2 metric deliberately deferred — ROUGE-L vs. accepted answers

  The harness scaffolds rouge_vs_accepted() but does not run it, for three defensible reasons: (1) semantic mismatch — current summaries summarize the question/issue ("resolution unknown"), so
  ROUGE against an accepted answer would score the wrong thing; (2) cost — accepted-answer bodies were never ingested, and scanning the multi-GB posts_answers.body column would break the free-tier
  guardrail; (3) summarization of resolutions is itself a Phase-2+ feature. The rationale is encoded in code so the deferral is explicit, not an omission.

  ---
  6. Task 3 — Agentic System Design

  6.1 Tools (modular, thin, independently testable)

  The agent is a single ADK root agent (gemini-2.5-flash) exposing the pipeline as three tools. Each tool is a thin wrapper over an importable src/ module, and the docstring is the tool description
  the model reads:

  ┌────────────────────────────────────────────────┬────────────────────────────┬────────────────────────────────────────────────┐
  │                      Tool                      │      Backing service       │                    Contract                    │
  ├────────────────────────────────────────────────┼────────────────────────────┼────────────────────────────────────────────────┤
  │ extract_entities(ticket_text)                  │ Cloud NL API               │ {entities:[{name,type,salience,…}], sentiment} │
  ├────────────────────────────────────────────────┼────────────────────────────┼────────────────────────────────────────────────┤
  │ find_related_tickets(ticket_text, top_k)       │ BigQuery (SQL / GQL graph) │ [{id, title, shared_tags, score, url}] or []   │
  ├────────────────────────────────────────────────┼────────────────────────────┼────────────────────────────────────────────────┤
  │ summarize_ticket(ticket_text)                  │ Vertex AI / Gemini Flash   │ one grounded paragraph                         │
  ├────────────────────────────────────────────────┼────────────────────────────┼────────────────────────────────────────────────┤
  │ (Phase 2) get_resolution / cross-doc synthesis │ BigQuery + Gemini          │ "known issue & likely fix" citing multiple ids │
  └────────────────────────────────────────────────┴────────────────────────────┴────────────────────────────────────────────────┘

  Reliability contract: tools return []/empty gracefully on expected-empty cases (e.g., no precedent) and never raise into the agent loop — letting the agent reason about "no precedent → escalate"
  rather than crash.

  6.2 Reasoning / planning

  The agent's instruction enforces: treat the user's message as the ticket → extract_entities → find_related_tickets → ground the answer only in retrieved resolved tickets, citing every id/url → if
  nothing comes back, state no precedent and suggest escalation → never invent a fix or a ticket id. It asks a single clarifying question only when the message has no technical content.

  Agent reasoning flow:

  flowchart TD
      A[Incoming ticket / user query] --> B[extract_entities]
      B --> C{Entities + tags<br/>confident enough?}
      C -- No --> Q[Ask one clarifying question] --> A
      C -- Yes --> D[find_related_tickets]
      D --> E{Any resolved<br/>matches found?}
      E -- No --> F[Report no precedent;<br/>suggest escalation]
      E -- Yes --> H[summarize_ticket<br/>grounded brief]
      H --> I[Return brief + cited source tickets]

  6.3 State & memory

  - In-session: ADK session state holds extracted entities and retrieved candidates within a run (the agent "remembers" across tool calls in one conversation).
  - Cross-session (Phase 2 / roadmap): persist turns to Firestore (triage_sessions) keyed by user/thread, so a returning user's prior tickets and resolutions are recalled. Memorystore would back
  low-latency working memory; BigQuery remains the long-term analytical store. Agent Engine Memory Bank is the Phase-3 managed upgrade — documented, not built.

  6.4 Verified end-to-end behavior

  Run locally with adk web src/support_triage/agent. A live trace for "What's the likely fix for a ticket about Cloud Functions in Python failing to access Cloud Storage buckets?":

  - Agent called extract_entities → find_related_tickets (no hallucinated steps).
  - Retrieved a real, topically-exact resolved ticket — #56312091 "Accessing google cloud storage bucket from cloud functions throws 500 error" (3 shared tags) — and cited its id + URL.
  - A weaker query (Cloud Run 503s, only a single shared gcp tag) correctly produced "no precedent → escalate" rather than a fabricated fix — the grounding guardrail working as designed.

  ---
  7. High-Level GCP Architecture

  flowchart TB
      subgraph Public["Public data"]
          SO[("bigquery-public-data<br/>.stackoverflow")]
      end
      subgraph Storage["Working corpus (BigQuery)"]
          RAW[["tickets (sampled slice)"]]
          ENT[["entities"]]
          SUM[["summaries"]]
          PG{{"triage_graph<br/>(optional property graph)"}}
      end
      subgraph AI["GCP AI services"]
          NL["Cloud Natural Language API<br/>entities + sentiment"]
          GEM["Vertex AI - Gemini Flash<br/>summarization"]
      end
      subgraph Agent["Agent runtime (ADK, local)"]
          ROOT["Support-Triage Agent"]
          T1["tool: extract_entities"]
          T2["tool: find_related_tickets"]
          T3["tool: summarize_ticket"]
      end
      USER([User / incoming ticket])

      SO -- "sampled (make ingest)" --> RAW
      RAW --> NL --> ENT
      ENT --> PG
      RAW --> PG
      RAW --> GEM --> SUM
      USER --> ROOT
      ROOT --> T1 --> NL
      ROOT --> T2 --> RAW
      ROOT --> T3 --> GEM
      ROOT --> USER

  Retrieval as a property graph (the differentiator). The relationship "resolved questions that share tags/entities with this ticket, and the users who resolved them" is naturally a graph. Phase 1
  ships the equivalent BigQuery SQL (guaranteed); the GQL property graph (CREATE PROPERTY GRAPH + GRAPH_TABLE/MATCH) is the multi-hop generalization, which the retrieval tool prefers when built and
  falls back to SQL on any error (ADR 0003). Graph schema:

  erDiagram
      QUESTION ||--o{ ANSWER : "ANSWERED_BY"
      QUESTION }o--o{ TAG : "TAGGED_WITH"
      QUESTION }o--|| USER : "ASKED_BY"
      QUESTION }o--o{ ENTITY : "MENTIONS"
      QUESTION { int id PK
                 string title
                 bool is_resolved
                 float sentiment }
      TAG    { string name PK }
      ENTITY { string name PK
               string type }
      USER   { int id PK
               int reputation }

  Component → service mapping

  ┌──────────────────────┬─────────────────────────────────────┬────────────────────────────────────────────────────────┬──────┐
  │      Component       │             GCP service             │                       Why chosen                       │ ADR  │
  ├──────────────────────┼─────────────────────────────────────┼────────────────────────────────────────────────────────┼──────┤
  │ Corpus storage       │ BigQuery                            │ Dataset already hosted there; serverless; free tier    │ 0001 │
  ├──────────────────────┼─────────────────────────────────────┼────────────────────────────────────────────────────────┼──────┤
  │ Entities + sentiment │ Cloud Natural Language API          │ Managed, deterministic, free units, snapshot-testable  │ 0002 │
  ├──────────────────────┼─────────────────────────────────────┼────────────────────────────────────────────────────────┼──────┤
  │ Retrieval            │ BigQuery SQL (+ optional GQL graph) │ Relationship traversal with no new service to operate  │ 0003 │
  ├──────────────────────┼─────────────────────────────────────┼────────────────────────────────────────────────────────┼──────┤
  │ Summarization        │ Vertex AI — Gemini Flash            │ GCP-native, low cost, adequate grounded quality        │ 0004 │
  ├──────────────────────┼─────────────────────────────────────┼────────────────────────────────────────────────────────┼──────┤
  │ Orchestration        │ Google ADK                          │ Code-first tools, multi-step reasoning, local dev/demo │ 0006 │
  ├──────────────────────┼─────────────────────────────────────┼────────────────────────────────────────────────────────┼──────┤
  │ Cross-session memory │ Firestore (roadmap)                 │ Serverless document store keyed by session             │ 0006 │
  └──────────────────────┴─────────────────────────────────────┴────────────────────────────────────────────────────────┴──────┘

  ---
  8. Results, Challenges & Trade-offs

  What works today. A fully reproducible pipeline (ingest → extract → graph → summarize → agent → eval), an ADK agent that calls real tools and cites real ticket ids, and a stable quantitative
  metric plus a qualitative spot-check.

  Key trade-offs (each recorded as an ADR):

  1. NL API over LLM extraction (0002). Chose determinism, zero cost, and testability over an LLM's flexibility. Trade-off: fixed entity taxonomy. v2's dropped salience field was the surprise —
  handled with a mention-frequency proxy, then resolved by moving to v1 entity-sentiment in Phase 2.
  2. Graph retrieval, SQL-first (0003). The property graph is the elegant long-term model, but GQL is Pre-GA — so SQL is the guaranteed path and the graph is opportunistic with automatic fallback.
  We get architectural expressiveness without betting reliability on a preview feature.
  3. Text-overlap retrieval, not vectors (current). find_related_by_text ranks resolved tickets by tag-term overlap with the incoming free text. It's transparent and free but lexical — prose
  phrasing retrieves weakly versus tag-like phrasing. Hybrid semantic retrieval (Vertex embeddings + Vector Search) is the documented Phase-3 upgrade.
  4. Gemini Flash, never Pro (0004). Quality-for-cost; the thinking-token output-budget behavior was the main engineering gotcha (truncated summaries and a truncated eval-judge JSON), solved with
  generous caps, sentence-trimming, and tolerant score-parsing.
  5. Local ADK, not Agent Engine (0006). Develop and demo locally for a 48-hour scope; managed deployment is a productionization narrative, not prototype work.

  Honest limitations. Lexical retrieval; self-judge leniency in the qualitative eval; small sample (cost-bounded); summaries describe issues rather than synthesizing resolutions across precedents
  (the Phase-2 summarize_cluster tool is scaffolded but not yet wired).

  ---
  9. Productionization Approach (conceptual)

  How this prototype would extend to real-world deployment:

  Scalability & orchestration. Replace make targets with Vertex AI Pipelines for the batch extract/summarize/graph-build DAG (versioned, scheduled, cached). Drive event-driven ingestion with
  Pub/Sub (a new ticket → topic) and Cloud Functions / Cloud Run for per-ticket extraction and summarization, scaling to zero between bursts. Promote the agent from local ADK to Vertex AI Agent 
  Engine (managed runtime, autoscaling, tracing).

  Security & data privacy. Least-privilege IAM per component (separate service accounts for ingest, extraction, agent); CMEK encryption on BigQuery/GCS; VPC Service Controls to prevent
  exfiltration; Cloud DLP to redact PII from tickets before they reach the LLM; Secret Manager for any credentials. All config already comes from env vars — no hard-coded project ids or secrets.

  Monitoring, logging & error handling. Cloud Logging for structured tool traces, Cloud Monitoring dashboards + alerts on tool error-rate, p95 latency, and groundedness (share of answers citing a
  real ticket). Calls already use retry/backoff (with_backoff); add dead-letter queues for failed extractions and a circuit-breaker that degrades the graph path to SQL (already designed in).

  Cost management. The free-tier guardrails (ADR 0004) become budget controls: BigQuery --dry-run byte checks in CI, NL API document caps, Flash-only with batch-mode (50% off) for bulk jobs,
  embedding/summary caching to avoid recomputation, and BigQuery slot reservations only if volume warrants. Per-tool cost is logged as a label for showback.

  CI/CD & reproducibility. A lint → unit-test → evaluation-gate → deploy pipeline (the eval harness becomes a quality gate that blocks regressions in extraction F1 / summary groundedness). Pinned
  dependencies (requirements-lock.txt), containerized jobs, prompt + model versioning with the model recorded per artifact (already done — summaries.model). Every artifact regenerable from a single
  command — the prototype's core discipline scales directly into production.

  ---
  10. Reproducibility & Repository
  
  Everything is regenerable; no manual console clicking. Configuration is entirely env-driven (.env / .env.example).

  ┌───────────────┬───────────────────────────────────────────────────┬─────────────────────────────────┐
  │     Step      │                      Command                      │             Output              │
  ├───────────────┼───────────────────────────────────────────────────┼─────────────────────────────────┤
  │ Sample corpus │ make ingest                                       │ tickets table                   │
  ├───────────────┼───────────────────────────────────────────────────┼─────────────────────────────────┤
  │ Explore       │ make eda                                          │ EDA profile                     │
  ├───────────────┼───────────────────────────────────────────────────┼─────────────────────────────────┤
  │ Extract       │ make extract                                      │ entities table                  │
  ├───────────────┼───────────────────────────────────────────────────┼─────────────────────────────────┤
  │ Build graph   │ make build-graph                                  │ triage_graph + sample traversal │
  ├───────────────┼───────────────────────────────────────────────────┼─────────────────────────────────┤
  │ Summarize     │ make summarize                                    │ summaries table                 │
  ├───────────────┼───────────────────────────────────────────────────┼─────────────────────────────────┤
  │ Run agent     │ adk web src/support_triage/agent / make run-agent │ local agent UI                  │
  ├───────────────┼───────────────────────────────────────────────────┼─────────────────────────────────┤
  │ Evaluate      │ make eval                                         │ metrics + eval_results.md       │
  └───────────────┴───────────────────────────────────────────────────┴─────────────────────────────────┘

  ADR index: 0001 dataset choice · 0002 NL API vs LLM extraction · 0003 graph vs vector retrieval · 0004 cost & model selection · 0006 ADK orchestration. Stack: Python ≥3.11, ADK 2.2.0,
  google-cloud-bigquery, google-cloud-language, vertexai; ruff for lint/format; type hints + docstrings throughout. GCP resources required: a project with BigQuery, Cloud Natural Language API, and
  Vertex AI enabled; gcloud auth; ~free-tier footprint.