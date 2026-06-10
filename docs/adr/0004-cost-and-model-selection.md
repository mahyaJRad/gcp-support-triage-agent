# ADR 0004 - Cost strategy and Gemini model selection

## Status
Accepted

## Context
The prototype must run without out-of-pocket cost on a personal account, and it
needs a generation model for summarization. Model choice and cost are coupled:
the tier of Gemini dominates spend.

## Decision
Engineer every step to fit standing free tiers, and use **Gemini Flash**
(`gemini-2.5-flash`) on Vertex AI both for **summarization** and as the **ADK
agent's reasoning model**. Gemini draws on the new-account credit (cents at this
volume); BigQuery and the NL API stay free.

Flash is a deliberate **prototype cost choice, not a quality ceiling**: for a
48-hour prototype with short single-/few-document tasks it is adequate. The
production intent is **tiered model routing** - Flash for bulk and simple steps,
and a **frontier model (Gemini Pro / frontier tier) for complex multi-step agent
reasoning turns** (e.g. cross-document synthesis or ambiguous triage), where the
extra reasoning quality is worth the higher token cost.

## Budget guardrails
| Service | Free allowance | Usage here | Guardrail |
|---------|----------------|------------|-----------|
| BigQuery | 1 TB query / month | a few MB | sampling + column projection; `--dry-run` shows bytes |
| NL API | 5,000 units / month | <= ~300 docs | sample cap in `config.py` |
| Gemini (Vertex) | none (credit) | a few hundred Flash calls | Flash only, never Pro for batch |
| ADK | free (local) | local only | managed runtime is a roadmap item |

## Alternatives considered
- **Gemini Pro / frontier tier:** stronger reasoning at roughly 10-20x the token
  cost, unnecessary for single- and short multi-document summaries in this
  prototype. The production plan is to **route to it for complex multi-step agent
  turns** while keeping Flash as the default (see Decision).
- **Gemini Developer API (AI Studio) free tier:** free, but uses inputs for
  training and is not the enterprise GCP path. Vertex AI is used for the
  data-handling posture and a clean route to production.

## Consequences
- (+) Roughly zero cost; same SDK path productionizes cleanly to Vertex/Agent
  Engine later.
- (-) Sampling means results are illustrative, not corpus-complete - stated
  honestly in the report. Per-token Gemini cost is covered by the credit.
