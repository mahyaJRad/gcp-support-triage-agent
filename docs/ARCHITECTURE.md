# Architecture

## Scenario

A support team answers variations of the same technical questions repeatedly, and
the knowledge of how each was resolved is scattered across past tickets. The agent
shortens first-response time and keeps answers consistent: given a new ticket it
identifies the core issue, checks whether something similar was resolved before,
and drafts a grounded summary of the likely fix that cites its sources. When no
precedent exists it says so and suggests escalation rather than inventing an
answer.

## Approach

1. **Storage** - a tag-scoped sample of the public Stack Overflow dataset is
   copied into a working BigQuery dataset (cost-bounded; ADR 0001, 0004).
2. **Extraction** - the Cloud Natural Language API produces entities and
   document sentiment per ticket (ADR 0002).
3. **Retrieval** - resolved tickets sharing tags/entities are found by a BigQuery
   query; an optional GQL property graph expresses the same relationship for
   multi-hop traversals (ADR 0003).
4. **Summarization** - Gemini Flash on Vertex AI produces a grounded brief
   (ADR 0004).
5. **Orchestration** - an ADK agent exposes the above as tools and chains them
   (ADR 0006).

## Agentic workflow

- **Goal:** answer "what is the likely fix for this ticket?" using prior resolved
  tickets, or escalate when there is no precedent.
- **Tools:** `extract_entities` (NL API), `find_related_tickets` (BigQuery),
  `summarize_ticket` (Gemini).
- **Reasoning:** extract -> clarify if the ticket is ambiguous -> retrieve ->
  escalate if nothing resolved is found -> summarize with citations.
- **State:** ADK session state within a run; optional Firestore persistence
  across sessions (roadmap).

## Diagrams

All diagrams are Mermaid (render on GitHub, in VS Code, or at mermaid.live).

### High-level GCP topology

```mermaid
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
```

### Agent reasoning flow

```mermaid
flowchart TD
    A[Incoming ticket / user query] --> B[extract_entities]
    B --> C{Entities + tags<br/>confident enough?}
    C -- No --> Q[Ask one clarifying question] --> A
    C -- Yes --> D[find_related_tickets]
    D --> E{Any resolved<br/>matches found?}
    E -- No --> F[Report no precedent;<br/>suggest escalation]
    E -- Yes --> H[summarize_ticket<br/>grounded brief]
    H --> I[Return brief + cited source tickets]
```

### Retrieval as a property graph

The retrieval relationship - resolved questions that share tags/entities with a
ticket, and the users who resolved them - is naturally a graph. Phase 1 ships the
equivalent BigQuery SQL; the graph is the multi-hop generalization (ADR 0003).

```mermaid
erDiagram
    QUESTION ||--o{ ANSWER : "ANSWERED_BY"
    QUESTION }o--o{ TAG : "TAGGED_WITH"
    QUESTION }o--|| USER : "ASKED_BY"
    QUESTION }o--o{ ENTITY : "MENTIONS"
    QUESTION {
        int    id PK
        string title
        bool   is_resolved
        float  sentiment
    }
    TAG    { string name PK }
    ENTITY { string name PK
             string type }
    USER   { int id PK
             int reputation }
```

## Component to service mapping

| Component | Service | Rationale | ADR |
|-----------|---------|-----------|-----|
| Corpus storage | BigQuery | Dataset already hosted there; serverless; free tier | 0001 |
| Entities + sentiment | Cloud Natural Language API | Managed, deterministic, free units | 0002 |
| Retrieval | BigQuery SQL (+ optional GQL graph) | Relationship traversal without a new service | 0003 |
| Summarization | Gemini Flash / Vertex AI | GCP-native, low cost, adequate quality | 0004 |
| Orchestration | ADK | Code-first tools, multi-step reasoning, local dev | 0006 |

## Evaluation

Stack Overflow tags are a free gold standard. Extraction is scored by
precision/recall of extracted entities against a ticket's tags; summaries get a
small qualitative spot-check (faithfulness and usefulness). NL API output and SQL
retrieval are deterministic and snapshot-testable; Gemini output is checked for
properties (non-empty, cites a ticket id, no invented fix) rather than exact text.
