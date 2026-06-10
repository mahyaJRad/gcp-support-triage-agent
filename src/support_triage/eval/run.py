"""Evaluation harness (see docs/ARCHITECTURE.md "Evaluation").

Two metrics, matching the rubric:
  * Quantitative - precision/recall/F1 of extracted entities against Stack
    Overflow tags as a free gold standard, over the sample.
  * Qualitative  - a small spot-check of summaries scored for faithfulness and
    usefulness (1-5) by a Gemini-Flash judge, rendered as a markdown table for
    the report.

Phase 2 (ROUGE-L of summaries vs accepted answers) is deferred on purpose; see
``rouge_vs_accepted`` for the rationale.

    python -m support_triage.eval.run          # or: make eval
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from support_triage.config import CONFIG

# Where the qualitative table is persisted so the report can pick it up.
RESULTS_PATH = Path(__file__).resolve().parents[3] / "eval_results.md"


def _toks(s: str) -> set[str]:
    """Alphanumeric tokens, lowercased; splits 'google-cloud-platform' into parts."""
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


# --------------------------------------------------------------------------- #
# Quantitative: entity / tag overlap
# --------------------------------------------------------------------------- #
def entity_tag_overlap() -> dict:
    """Precision/recall/F1 of extracted entities against Stack Overflow tags as the
    gold standard, over the sample.

    A tag and an entity match when their token sets intersect (so "Google Cloud"
    matches "google-cloud-platform"). Micro-averaged:
      precision = entities matching some tag / all entities
      recall    = tags matched by some entity / all tags
    Returns {precision, recall, f1, n_tickets}.
    """
    from support_triage.gcp import bq_client

    client = bq_client()
    ents = client.query(
        f"SELECT ticket_id, entity_name FROM `{CONFIG.entities_table}` "
        "WHERE entity_name IS NOT NULL",
        location=CONFIG.bq_location,
    ).to_dataframe()
    tix = client.query(
        f"SELECT id, tags FROM `{CONFIG.tickets_table}`",
        location=CONFIG.bq_location,
    ).to_dataframe()

    tags_by_id = {int(r.id): str(r.tags).split("|") for r in tix.itertuples()}
    ents_by_id: dict[int, list[str]] = {}
    for r in ents.itertuples():
        ents_by_id.setdefault(int(r.ticket_id), []).append(r.entity_name)

    tp_ent = n_ent = tp_tag = n_tag = 0
    for tid, entity_names in ents_by_id.items():
        gold_tok = [_toks(t) for t in tags_by_id.get(tid, [])]
        ent_tok = [_toks(e) for e in entity_names]
        n_ent += len(ent_tok)
        n_tag += len(gold_tok)
        tp_ent += sum(1 for et in ent_tok if any(et & gt for gt in gold_tok))
        tp_tag += sum(1 for gt in gold_tok if any(gt & et for et in ent_tok))

    precision = tp_ent / n_ent if n_ent else 0.0
    recall = tp_tag / n_tag if n_tag else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "n_tickets": len(ents_by_id),
    }


# --------------------------------------------------------------------------- #
# Qualitative: summary faithfulness / usefulness spot-check
# --------------------------------------------------------------------------- #
_JUDGE_PROMPT = (
    "You are grading a one-paragraph SUMMARY of a technical support ticket against "
    "the original TICKET it was written from. Score two axes from 1 (poor) to 5 "
    "(excellent):\n"
    "  faithful - every claim in the summary is supported by the ticket; no "
    "invented facts or fixes. A summary that correctly says the resolution is "
    "unknown is still faithful.\n"
    "  useful   - how well the summary would help a support engineer quickly "
    "grasp and triage the issue.\n"
    "Reply with ONLY a JSON object: "
    '{{"faithful": <int>, "useful": <int>, "note": "<=12 word justification>"}}.\n\n'
    "TICKET:\n{body}\n\nSUMMARY:\n{summary}\n"
)


def _judge(body: str, summary: str) -> dict:
    """Score one (ticket, summary) pair with the Gemini-Flash judge (temp 0).

    Returns {faithful, useful, note}. On any model/parse error returns zeros with
    the error in `note` so the table still renders rather than aborting `make eval`.
    """
    from vertexai.generative_models import GenerationConfig

    from support_triage.gcp import with_backoff
    from support_triage.summarization.gemini import _model

    try:
        # gemini-2.5-flash is a thinking model: reasoning draws from the output
        # budget, so a small cap truncates the JSON. 1024 leaves ample room.
        resp = with_backoff(
            _model().generate_content,
            _JUDGE_PROMPT.format(body=body, summary=summary),
            generation_config=GenerationConfig(temperature=0.0, max_output_tokens=1024),
        )
        match = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
        return {
            "faithful": int(data["faithful"]),
            "useful": int(data["useful"]),
            "note": str(data.get("note", "")).strip(),
        }
    except Exception as e:  # judge is best-effort; never break the harness
        return {"faithful": 0, "useful": 0, "note": f"judge error: {type(e).__name__}"}


def summary_spotcheck(n: int = 5) -> list[dict]:
    """Score n summaries for faithfulness and usefulness (1-5) against their source
    ticket body. Returns [{ticket_id, title, summary, faithful, useful, note}]."""
    from support_triage.gcp import bq_client

    rows = (
        bq_client()
        .query(
            f"""
        SELECT s.ticket_id, s.title, s.summary, t.body_clean AS body
        FROM `{CONFIG.summaries_table}` s
        JOIN `{CONFIG.tickets_table}` t ON t.id = s.ticket_id
        ORDER BY s.ticket_id
        LIMIT {n}
        """,
            location=CONFIG.bq_location,
        )
        .result()
    )

    out = []
    for r in rows:
        scores = _judge(r["body"] or "", r["summary"] or "")
        out.append(
            {
                "ticket_id": r["ticket_id"],
                "title": r["title"],
                "summary": r["summary"],
                **scores,
            }
        )
    return out


def _spotcheck_markdown(rows: list[dict]) -> str:
    """Render the spot-check rows as a markdown table for the report."""

    def esc(s: str) -> str:
        return str(s).replace("|", "\\|").replace("\n", " ").strip()

    n = len(rows)
    f_avg = sum(r["faithful"] for r in rows) / n if n else 0.0
    u_avg = sum(r["useful"] for r in rows) / n if n else 0.0
    lines = [
        "## Summary spot-check (Gemini-Flash judge, 1-5)",
        "",
        f"Mean faithfulness **{f_avg:.1f}/5**, mean usefulness **{u_avg:.1f}/5** "
        f"over {n} summaries.",
        "",
        "| Ticket | Summary | Faithful | Useful | Note |",
        "|--------|---------|:--------:|:------:|------|",
    ]
    for r in rows:
        lines.append(
            f"| [{r['ticket_id']}](https://stackoverflow.com/q/{r['ticket_id']}) "
            f"| {esc(r['summary'])} | {r['faithful']} | {r['useful']} | {esc(r['note'])} |"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Phase 2 (deferred): ROUGE-L of summaries vs accepted answers
# --------------------------------------------------------------------------- #
def rouge_vs_accepted() -> dict:
    """Deferred - not run by `make eval`. Three reasons:

    1. Semantic mismatch: the current summaries summarize the *question/issue*
       ("the resolution is unknown"), so ROUGE-L against an *accepted answer* would
       score the wrong thing (problem text vs resolution text).
    2. Cost: accepted-answer bodies were never ingested; computing this would mean
       scanning the multi-GB `posts_answers.body` column of the public dataset,
       which breaks the free-tier guardrail (Golden Rule #1).
    3. Summarization is being revisited; measure once it summarizes resolutions.

    To enable later: ingest accepted-answer text into the working dataset (a Phase-2
    data task), then ROUGE-L summary-vs-answer per ticket and average.
    """
    raise NotImplementedError("Phase 2: see docstring for why this is deferred")


def run() -> None:
    print("=" * 70)
    print("QUANTITATIVE - entity/tag overlap (gold standard = Stack Overflow tags)")
    print("=" * 70)
    print(entity_tag_overlap())

    print("\n" + "=" * 70)
    print("QUALITATIVE - summary faithfulness / usefulness spot-check")
    print("=" * 70)
    rows = summary_spotcheck(5)
    table = _spotcheck_markdown(rows)
    print("\n" + table)
    RESULTS_PATH.write_text(table + "\n", encoding="utf-8")
    print(f"\n[eval] wrote qualitative table -> {RESULTS_PATH}")

    print("\n" + "=" * 70)
    print("PHASE 2 - ROUGE-L vs accepted answers: DEFERRED")
    print("=" * 70)
    print("  Summaries describe the issue, not the resolution, and accepted-answer")
    print("  text was never ingested (scanning it would break the free-tier budget).")
    print("  Enable after a Phase-2 answer-text ingest; see rouge_vs_accepted().")


if __name__ == "__main__":
    run()
