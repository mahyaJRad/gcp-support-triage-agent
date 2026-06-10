# ADR 0001 - Dataset: Stack Overflow questions as support tickets

## Status
Accepted

## Context
The system needs an unstructured-text corpus. Selection criteria: already hosted
on GCP, a built-in gold standard for evaluation, a structure that justifies
relationship-based retrieval, and a clean multi-document agent scenario.

## Decision
Use `bigquery-public-data.stackoverflow`, modeling questions as support tickets:
title = subject, body = issue, tags = category, accepted answer = resolution.

## Alternatives considered
- **Product reviews (Amazon/IMDB):** strong for entity sentiment, but retrieval
  is not relationship-shaped, so a graph would be contrived.
- **News (GDELT):** strong NER, but event-metadata heavy and operationally fiddly.
- **Scientific abstracts:** domain language is hard to evaluate without expertise.

## Consequences
- (+) Already in BigQuery, so ingestion is a scoped SQL query rather than file
  wrangling.
- (+) Tags provide a free multi-label gold standard for extraction evaluation.
- (+) Naturally graph-shaped (users, questions, tags, answers).
- (+) "Have we solved this before?" is a crisp multi-document agent scenario.
- (-) Entities skew technical (product/tech names) rather than rich NER; the NL
  API still runs and results are reported honestly.
