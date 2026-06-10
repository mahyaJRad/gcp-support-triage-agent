"""Evaluation harness (see docs/ARCHITECTURE.md "Evaluation").

Metrics, matching the rubric:
  * Quantitative - precision/recall/F1 of extracted entities against Stack
    Overflow tags as a free gold standard, over the sample. The managed Cloud
    Natural Language API is scored side-by-side with a traditional spaCy NER
    baseline on the same documents.
  * Qualitative  - a small spot-check of summaries scored for faithfulness and
    usefulness (1-5) by a Gemini-Flash judge, rendered as a markdown table for
    the report.

Phase 2 (ROUGE-L of summaries vs accepted answers) is deferred on purpose; see
``rouge_vs_accepted`` for the rationale.

    python -m support_triage.eval.run                    # or: make eval
    python -m support_triage.eval.run --extraction-only  # or: make baseline
"""

from __future__ import annotations

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
def _micro_prf(ents_by_id: dict[int, list[str]], tags_by_id: dict[int, list[str]]) -> dict:
    """Micro-averaged precision/recall/F1 of extracted entities vs gold tags.

    An entity and a tag match when their token sets intersect (so "Google Cloud"
    matches "google-cloud-platform"):
      precision = entities matching some tag / all entities
      recall    = tags matched by some entity / all tags
    Shared by the NL API and spaCy baselines so the two are directly comparable.
    Returns {precision, recall, f1, n_tickets}.
    """
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

    return _micro_prf(ents_by_id, tags_by_id)


def entity_tag_overlap_spacy() -> dict:
    """Same entity/tag-overlap metric as ``entity_tag_overlap``, but using the
    spaCy NER baseline instead of the NL API.

    Runs over the SAME tickets the NL API extracted (the ids in the entities
    table) and rebuilds each document the way extraction did
    (``truncate(title + clean_html(body))``) for an apples-to-apples comparison.
    spaCy runs locally, so this adds no GCP cost. Returns {precision, recall,
    f1, n_tickets}.
    """
    from support_triage.data.preprocess import clean_html, truncate
    from support_triage.extraction.baseline_spacy import extract_spacy
    from support_triage.gcp import bq_client

    rows = (
        bq_client()
        .query(
            f"""
        SELECT id, title, body, tags
        FROM `{CONFIG.tickets_table}`
        WHERE id IN (SELECT DISTINCT ticket_id FROM `{CONFIG.entities_table}`)
        """,
            location=CONFIG.bq_location,
        )
        .result()
    )

    tags_by_id: dict[int, list[str]] = {}
    ents_by_id: dict[int, list[str]] = {}
    for r in rows:
        tid = int(r["id"])
        text = truncate(f"{r['title']}. {clean_html(r['body'])}")
        tags_by_id[tid] = str(r["tags"]).split("|")
        ents_by_id[tid] = [e["name"] for e in extract_spacy(text)]

    return _micro_prf(ents_by_id, tags_by_id)


def _extraction_comparison_markdown(nl: dict, sp: dict) -> str:
    """Render the NL API vs spaCy entity/tag-overlap scores as a markdown table."""
    return "\n".join(
        [
            "## Extraction baseline comparison (entities vs Stack Overflow tags)",
            "",
            f"Micro-averaged precision/recall/F1 over {nl['n_tickets']} tickets, scored "
            "against each ticket's tags as a free gold standard (same documents for both).",
            "",
            "| Extractor | Precision | Recall | F1 |",
            "|-----------|:---------:|:------:|:--:|",
            f"| Cloud Natural Language API | {nl['precision']} | {nl['recall']} | {nl['f1']} |",
            f"| spaCy `en_core_web_sm` | {sp['precision']} | {sp['recall']} | {sp['f1']} |",
        ]
    )


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
        # budget, so a too-small cap can truncate the reply (finish=MAX_TOKENS).
        resp = with_backoff(
            _model().generate_content,
            _JUDGE_PROMPT.format(body=body, summary=summary),
            generation_config=GenerationConfig(temperature=0.0, max_output_tokens=1536),
        )
        text = resp.text or ""

        # Pull the two integer scores directly. They precede the verbose `note`,
        # so this still works even if a thinking-token spike truncates the JSON
        # mid-`note` (no closing brace) - more robust than json.loads of the whole.
        def _score(key: str) -> int | None:
            m = re.search(rf'"{key}"\s*:\s*([1-5])', text)
            return int(m.group(1)) if m else None

        faithful, useful = _score("faithful"), _score("useful")
        note_m = re.search(r'"note"\s*:\s*"([^"]*)', text)  # tolerate truncated tail
        note = note_m.group(1).strip() if note_m else ""
        if faithful is None or useful is None:
            return {"faithful": 0, "useful": 0, "note": "judge error: no score parsed"}
        return {"faithful": faithful, "useful": useful, "note": note}
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


def extraction_comparison() -> str:
    """Score the NL API and the spaCy baseline on the same tickets, print and
    return the comparison table. No Gemini cost - handy as a standalone check
    (`make baseline`)."""
    print("=" * 70)
    print("QUANTITATIVE - entity/tag overlap (gold standard = Stack Overflow tags)")
    print("=" * 70)
    nl = entity_tag_overlap()
    sp = entity_tag_overlap_spacy()
    print(f"  Cloud Natural Language API : {nl}")
    print(f"  spaCy en_core_web_sm       : {sp}")
    table = _extraction_comparison_markdown(nl, sp)
    print("\n" + table)
    return table


def run(extraction_only: bool = False) -> None:
    extraction_table = extraction_comparison()

    if extraction_only:
        RESULTS_PATH.write_text(extraction_table + "\n", encoding="utf-8")
        print(f"\n[eval] wrote extraction comparison -> {RESULTS_PATH}")
        return

    print("\n" + "=" * 70)
    print("QUALITATIVE - summary faithfulness / usefulness spot-check")
    print("=" * 70)
    rows = summary_spotcheck(5)
    spot_table = _spotcheck_markdown(rows)
    print("\n" + spot_table)
    RESULTS_PATH.write_text(extraction_table + "\n\n" + spot_table + "\n", encoding="utf-8")
    print(f"\n[eval] wrote extraction + qualitative tables -> {RESULTS_PATH}")

    print("\n" + "=" * 70)
    print("PHASE 2 - ROUGE-L vs accepted answers: DEFERRED")
    print("=" * 70)
    print("  Summaries describe the issue, not the resolution, and accepted-answer")
    print("  text was never ingested (scanning it would break the free-tier budget).")
    print("  Enable after a Phase-2 answer-text ingest; see rouge_vs_accepted().")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Evaluate extraction + summaries.")
    p.add_argument(
        "--extraction-only",
        action="store_true",
        help="only run the NL API vs spaCy extraction comparison (no Gemini cost)",
    )
    args = p.parse_args()
    run(extraction_only=args.extraction_only)
