# ADR 0002 - Entity and sentiment extraction via Cloud Natural Language API

## Status
Accepted

## Context
Each ticket needs entities and sentiment. Two routes: the managed Natural
Language API, or prompting an LLM (Gemini) to emit structured entities.

## Decision
Use the **Cloud Natural Language API** for entity analysis and document
sentiment. An LLM-extraction path is kept only as a documented future option.

## Note on the API version
The v2 API does not return the `salience` field that v1 did. Entity prominence is
approximated by normalized mention frequency (entities mentioned more often rank
higher), which preserves the ranking semantics salience provided.

## Alternatives considered
- **Gemini structured extraction:** flexible and good at "core issue," but
  non-deterministic, needs schema-validation glue, and consumes paid tokens.
- **spaCy / TextRank:** a useful offline baseline for comparison, not the primary.

## Consequences
- (+) Managed, deterministic, 5,000 free units/month.
- (+) Cleanly separates structured extraction (NL API) from generation (Gemini).
- (-) Fixed entity taxonomy; the "core issue" abstraction is left to Gemini, so
  NL API handles entities/sentiment and Gemini handles the issue summary.
