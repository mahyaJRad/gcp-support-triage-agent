"""Evaluation harness (see docs/ARCHITECTURE.md "Evaluation").

Metrics, matching the rubric:
  * Quantitative - precision/recall/F1 of extracted entities against Stack
    Overflow tags as a free gold standard, over the sample. Three extractors are
    scored side-by-side on the same documents: the managed Cloud Natural Language
    API, a traditional spaCy NER baseline, and (optionally) a Gemini Flash LLM
    extractor. The Gemini row costs one Flash call per ticket, so it is capped at
    CONFIG.gemini_eval_docs and included only when requested (on by default for
    the full eval, off for the cheap --extraction-only path).
  * Qualitative  - summaries scored for faithfulness and usefulness (1-5) by a
    Gemini-Flash judge. To keep the LLM-judge honest rather than self-flattering,
    three things back the headline number: (a) a spot-check over a sample that
    spans the summary-length range (not cherry-picked); (b) a discrimination probe
    that injects a fabricated fix into real summaries and confirms faithfulness
    drops (the metric can tell good from bad); and (c) calibration of the judge
    against independent reference labels (agreement / MAE), so "faithfulness 4.6"
    is credible rather than self-graded.
    All render as markdown tables for the report.

Phase 2 (ROUGE-L of summaries vs accepted answers) is deferred on purpose; see
``rouge_vs_accepted`` for the rationale.

    python -m support_triage.eval.run                    # or: make eval
    python -m support_triage.eval.run --extraction-only  # or: make baseline
"""

from __future__ import annotations

import os
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


def entity_tag_overlap_gemini(max_docs: int | None = None) -> dict:
    """Same entity/tag-overlap metric as ``entity_tag_overlap``, but using the
    Gemini Flash LLM extractor instead of the NL API.

    One Flash call per ticket, so this is capped at ``max_docs`` (default
    ``CONFIG.gemini_eval_docs``) to bound cost. Scores the most-viewed tickets
    among those the NL API already extracted, rebuilding each document the way
    extraction did (``truncate(title + clean_html(body))``) for an
    apples-to-apples comparison. Returns {precision, recall, f1, n_tickets}.
    """
    from support_triage.data.preprocess import clean_html, truncate
    from support_triage.extraction.gemini_extract import extract_gemini
    from support_triage.gcp import bq_client

    cap = max_docs if max_docs is not None else CONFIG.gemini_eval_docs
    rows = (
        bq_client()
        .query(
            f"""
        SELECT id, title, body, tags
        FROM `{CONFIG.tickets_table}`
        WHERE id IN (SELECT DISTINCT ticket_id FROM `{CONFIG.entities_table}`)
        ORDER BY view_count DESC
        LIMIT {cap}
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
        ents_by_id[tid] = [e["name"] for e in extract_gemini(text)]

    return _micro_prf(ents_by_id, tags_by_id)


def _extraction_comparison_markdown(nl: dict, sp: dict, gem: dict | None = None) -> str:
    """Render the entity/tag-overlap scores as a markdown table.

    Always includes the managed NL API and the spaCy baseline; includes the
    Gemini Flash LLM baseline as a third row when ``gem`` is supplied. The
    Gemini row is scored over fewer tickets (one Flask call each is costly), so
    a per-row ticket count is shown to keep the comparison honest.
    """
    lines = [
        "## Extraction baseline comparison (entities vs Stack Overflow tags)",
        "",
        "Micro-averaged precision/recall/F1, scored against each ticket's tags as a "
        "free gold standard (same documents per extractor; see Tickets column).",
        "",
        "| Extractor | Tickets | Precision | Recall | F1 |",
        "|-----------|:-------:|:---------:|:------:|:--:|",
        f"| Cloud Natural Language API | {nl['n_tickets']} | {nl['precision']} | "
        f"{nl['recall']} | {nl['f1']} |",
        f"| spaCy `en_core_web_sm` | {sp['n_tickets']} | {sp['precision']} | "
        f"{sp['recall']} | {sp['f1']} |",
    ]
    if gem is not None:
        lines.append(
            f"| Gemini Flash (LLM) | {gem['n_tickets']} | {gem['precision']} | "
            f"{gem['recall']} | {gem['f1']} |"
        )
    return "\n".join(lines)


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


def _spotcheck_sample(n: int) -> list[dict]:
    """Pull n (ticket, summary) pairs that span the summary-length range, so the
    sample includes both easy (short) and hard (long, hallucination-prone)
    summaries rather than n arbitrary ones.

    Fetches a bounded pool ordered by summary length and picks n evenly-spaced
    rows across it. Returns [{ticket_id, title, summary, body}].
    """
    from support_triage.gcp import bq_client

    pool = list(
        bq_client()
        .query(
            f"""
        SELECT s.ticket_id, s.title, s.summary, t.body_clean AS body
        FROM `{CONFIG.summaries_table}` s
        JOIN `{CONFIG.tickets_table}` t ON t.id = s.ticket_id
        WHERE s.summary IS NOT NULL
        ORDER BY CHAR_LENGTH(s.summary)
        LIMIT 500
        """,
            location=CONFIG.bq_location,
        )
        .result()
    )
    if not pool:
        return []
    if n >= len(pool):
        picks = pool
    else:  # evenly spaced indices across the length-sorted pool (short..long)
        step = (len(pool) - 1) / (n - 1) if n > 1 else 0
        picks = [pool[round(i * step)] for i in range(n)]
    return [
        {
            "ticket_id": r["ticket_id"],
            "title": r["title"],
            "summary": r["summary"],
            "body": r["body"],
        }
        for r in picks
    ]


def summary_spotcheck(n: int | None = None) -> list[dict]:
    """Score n summaries for faithfulness and usefulness (1-5) against their source
    ticket body. n defaults to ``CONFIG.eval_spotcheck_docs``; the sample spans the
    summary-length range (see ``_spotcheck_sample``) so it is not cherry-picked.
    Returns [{ticket_id, title, summary, faithful, useful, note}]."""
    n = n if n is not None else CONFIG.eval_spotcheck_docs
    out = []
    for r in _spotcheck_sample(n):
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
    f = [r["faithful"] for r in rows]
    u = [r["useful"] for r in rows]
    f_avg = sum(f) / n if n else 0.0
    u_avg = sum(u) / n if n else 0.0
    lines = [
        "## Summary spot-check (Gemini-Flash judge, 1-5)",
        "",
        f"Mean faithfulness **{f_avg:.2f}/5** (range {min(f) if f else 0}-{max(f) if f else 0}), "
        f"mean usefulness **{u_avg:.2f}/5** (range {min(u) if u else 0}-{max(u) if u else 0}) "
        f"over {n} summaries, sampled across the summary-length range (not cherry-picked).",
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
# Discrimination probe: does the judge actually catch a hallucination?
# --------------------------------------------------------------------------- #
# A fabricated, specific "resolution" that appears in NONE of the tickets. A
# faithfulness judge worth trusting must score a summary carrying this claim
# strictly lower than the clean original.
_HALLUCINATION = (
    " The issue was definitively resolved by setting `retry_timeout=300` in the "
    "client constructor and downgrading the SDK to version 1.2.0, as confirmed by "
    "the accepted answer."
)


def _inject_hallucination(summary: str) -> str:
    """Append a concrete, unsupported fix to a summary to create a known-bad case."""
    return (summary or "").rstrip() + _HALLUCINATION


def discrimination_probe(k: int | None = None) -> dict:
    """Confirm the judge *discriminates*: corrupt k real summaries with a fabricated
    fix and check the faithfulness score drops.

    For each of k summaries (spanning the length range) we judge the clean
    original and a hallucination-injected copy. Returns
    {rows, k, mean_orig, mean_corrupt, detected} where ``detected`` counts cases
    whose faithfulness fell when the lie was added. Two judge calls per summary.
    """
    k = k if k is not None else CONFIG.eval_discrimination_docs
    rows = []
    for r in _spotcheck_sample(k):
        clean = _judge(r["body"] or "", r["summary"] or "")
        dirty = _judge(r["body"] or "", _inject_hallucination(r["summary"] or ""))
        rows.append(
            {
                "ticket_id": r["ticket_id"],
                "faithful_orig": clean["faithful"],
                "faithful_corrupt": dirty["faithful"],
                "caught": dirty["faithful"] < clean["faithful"],
                "note": dirty["note"],
            }
        )
    n = len(rows) or 1
    return {
        "rows": rows,
        "k": len(rows),
        "mean_orig": sum(r["faithful_orig"] for r in rows) / n,
        "mean_corrupt": sum(r["faithful_corrupt"] for r in rows) / n,
        "detected": sum(1 for r in rows if r["caught"]),
    }


def _discrimination_markdown(probe: dict) -> str:
    """Render the discrimination probe as a markdown table for the report."""
    rows = probe["rows"]
    lines = [
        "## Judge discrimination probe (does faithfulness catch hallucinations?)",
        "",
        f"Each of {probe['k']} real summaries was re-scored after injecting one "
        "fabricated fix absent from the ticket. A trustworthy faithfulness metric "
        "must penalise the corrupted version.",
        "",
        f"Mean faithfulness dropped **{probe['mean_orig']:.2f} -> "
        f"{probe['mean_corrupt']:.2f}/5**; the lie was caught in "
        f"**{probe['detected']}/{probe['k']}** cases.",
        "",
        "| Ticket | Faithful (clean) | Faithful (+lie) | Caught? | Judge note on corrupted |",
        "|--------|:----------------:|:---------------:|:-------:|-------------------------|",
    ]
    for r in rows:
        note = str(r["note"]).replace("|", "\\|").replace("\n", " ").strip()
        lines.append(
            f"| [{r['ticket_id']}](https://stackoverflow.com/q/{r['ticket_id']}) "
            f"| {r['faithful_orig']} | {r['faithful_corrupt']} "
            f"| {'yes' if r['caught'] else 'NO'} | {note} |"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Calibration: LLM judge vs an independent reference annotator
# --------------------------------------------------------------------------- #
# Reference labels live here as JSONL: one
# {"ticket_id", "summary", "faithful", "useful"} object per line, scored by a
# human annotator *independent of the judge*. Regenerate the template with
# write_label_template / `make eval-labels` and fill in the 1-5 scores by hand.
# The point is cross-checking the judge against a separate human rater, not
# self-grading - human labels make the strongest claim that the judge is honest.
LABELS_PATH = Path(__file__).resolve().parent / "reference_labels.jsonl"
# Stated provenance of the labels, surfaced in the report so the reader knows the
# calibration is anchored against a human rather than another model.
LABELS_PROVENANCE = os.environ.get(
    "EVAL_LABELS_PROVENANCE",
    "human annotator (independent of the Gemini judge)",
)


def write_label_template(n: int | None = None, path: Path = LABELS_PATH) -> int:
    """Write a JSONL template of n (ticket, summary) pairs for a reference rater
    to label.

    Each line has null ``faithful``/``useful`` for the rater to fill in 1-5. Won't
    clobber an existing labels file. Returns the number of rows written.
    """
    import json

    if path.exists():
        raise FileExistsError(f"{path} exists; refusing to overwrite reference labels")
    n = n if n is not None else CONFIG.eval_spotcheck_docs
    sample = _spotcheck_sample(n)
    with path.open("w", encoding="utf-8") as fh:
        for r in sample:
            fh.write(
                json.dumps(
                    {
                        "ticket_id": r["ticket_id"],
                        "summary": r["summary"],
                        "faithful": None,  # rater: 1-5
                        "useful": None,  # rater: 1-5
                    }
                )
                + "\n"
            )
    return len(sample)


def _load_reference_labels(path: Path = LABELS_PATH) -> list[dict]:
    """Read fully-labelled rows (both scores filled, 1-5) from the JSONL file.
    Returns [] if the file is missing or has no completed rows."""
    import json

    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row.get("faithful"), int) and isinstance(row.get("useful"), int):
            out.append(row)
    return out


def judge_calibration(path: Path = LABELS_PATH) -> dict | None:
    """Agreement of the Gemini judge with an independent reference annotator, so
    the spot-check numbers are calibrated rather than self-graded.

    Re-judges each labelled (ticket, summary) pair and compares to the reference
    score on both axes. Returns {n, faithful:{mae, within1, exact},
    useful:{...}} or None if no completed labels exist (calibration skipped).
    """
    labels = _load_reference_labels(path)
    if not labels:
        return None

    from support_triage.gcp import bq_client

    ids = sorted({int(r["ticket_id"]) for r in labels})
    body_rows = (
        bq_client()
        .query(
            f"SELECT id, body_clean FROM `{CONFIG.tickets_table}` "
            f"WHERE id IN ({','.join(str(i) for i in ids)})",
            location=CONFIG.bq_location,
        )
        .result()
    )
    body_by_id = {int(r["id"]): r["body_clean"] for r in body_rows}

    def _agreement(pairs: list[tuple[int, int]]) -> dict:
        n = len(pairs) or 1
        return {
            "mae": round(sum(abs(h - j) for h, j in pairs) / n, 2),
            "within1": round(sum(1 for h, j in pairs if abs(h - j) <= 1) / n, 2),
            "exact": round(sum(1 for h, j in pairs if h == j) / n, 2),
        }

    faith_pairs, use_pairs = [], []
    for lbl in labels:
        body = body_by_id.get(int(lbl["ticket_id"]), "")
        j = _judge(body or "", lbl["summary"] or "")
        if j["faithful"] == 0 and j["useful"] == 0:  # judge error row; skip
            continue
        faith_pairs.append((lbl["faithful"], j["faithful"]))
        use_pairs.append((lbl["useful"], j["useful"]))

    return {
        "n": len(faith_pairs),
        "faithful": _agreement(faith_pairs),
        "useful": _agreement(use_pairs),
    }


def _calibration_markdown(cal: dict | None) -> str:
    """Render the judge-vs-reference agreement, or a how-to note if unlabelled."""
    if cal is None:
        return (
            "## Judge calibration vs independent reference labels\n\n"
            "_Not run: no completed reference labels found._ Generate a template with "
            "`make eval-labels`, fill in `faithful`/`useful` (1-5) for ~10 rows in "
            f"`{LABELS_PATH.name}`, then re-run `make eval` to report agreement."
        )
    return "\n".join(
        [
            "## Judge calibration vs independent reference labels",
            "",
            f"Gemini-judge scores vs reference labels by an {LABELS_PROVENANCE}, over "
            f"{cal['n']} summaries. MAE = mean absolute error (0 = perfect); within-1 = "
            "fraction within 1 point; exact = fraction identical. Independent labels "
            "(ideally human) keep the judge honest rather than self-graded.",
            "",
            "| Axis | MAE | Within 1 | Exact |",
            "|------|:---:|:--------:|:-----:|",
            f"| Faithful | {cal['faithful']['mae']} | {cal['faithful']['within1']} "
            f"| {cal['faithful']['exact']} |",
            f"| Useful | {cal['useful']['mae']} | {cal['useful']['within1']} "
            f"| {cal['useful']['exact']} |",
        ]
    )


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


def extraction_comparison(with_gemini: bool = False) -> str:
    """Score the extractors on the same tickets, print and return the comparison
    table.

    Always scores the managed NL API and the free spaCy baseline (this is
    `make baseline`, with no Gemini cost). When ``with_gemini`` is set, also
    scores the Gemini Flash LLM extractor over ``CONFIG.gemini_eval_docs``
    tickets (one Flash call each); a Gemini failure is logged and the row is
    dropped rather than breaking the NL-API/spaCy comparison.
    """
    print("=" * 70)
    print("QUANTITATIVE - entity/tag overlap (gold standard = Stack Overflow tags)")
    print("=" * 70)
    nl = entity_tag_overlap()
    sp = entity_tag_overlap_spacy()
    print(f"  Cloud Natural Language API : {nl}")
    print(f"  spaCy en_core_web_sm       : {sp}")

    gem = None
    if with_gemini:
        try:
            gem = entity_tag_overlap_gemini()
            print(f"  Gemini Flash (LLM)         : {gem}")
        except Exception as e:  # keep the NL/spaCy table even if Gemini fails
            print(f"  Gemini Flash (LLM)         : SKIPPED ({type(e).__name__}: {e})")

    table = _extraction_comparison_markdown(nl, sp, gem)
    print("\n" + table)
    return table


def run(extraction_only: bool = False, with_gemini: bool | None = None) -> None:
    # Default: the full eval includes the Gemini extractor row; the cheap
    # `make baseline` (extraction_only) does not. Override via the CLI flags.
    if with_gemini is None:
        with_gemini = not extraction_only
    extraction_table = extraction_comparison(with_gemini=with_gemini)

    if extraction_only:
        RESULTS_PATH.write_text(extraction_table + "\n", encoding="utf-8")
        print(f"\n[eval] wrote extraction comparison -> {RESULTS_PATH}")
        return

    print("\n" + "=" * 70)
    print("QUALITATIVE - summary faithfulness / usefulness spot-check")
    print("=" * 70)
    rows = summary_spotcheck()
    spot_table = _spotcheck_markdown(rows)
    print("\n" + spot_table)

    print("\n" + "=" * 70)
    print("QUALITATIVE - judge discrimination probe (hallucination injection)")
    print("=" * 70)
    probe = discrimination_probe()
    disc_table = _discrimination_markdown(probe)
    print("\n" + disc_table)

    print("\n" + "=" * 70)
    print("QUALITATIVE - judge calibration vs independent reference labels")
    print("=" * 70)
    cal = judge_calibration()
    cal_table = _calibration_markdown(cal)
    print("\n" + cal_table)

    report = "\n\n".join([extraction_table, spot_table, disc_table, cal_table]) + "\n"
    RESULTS_PATH.write_text(report, encoding="utf-8")
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
        help="only run the extraction comparison (skips the summary spot-check)",
    )
    p.add_argument(
        "--make-labels",
        action="store_true",
        help="write a reference-label template (for judge calibration) and exit; "
        "no judging or cost",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--with-gemini",
        dest="with_gemini",
        action="store_true",
        default=None,
        help="include the Gemini Flash extractor row (default on for the full eval, "
        "off for --extraction-only; scores CONFIG.gemini_eval_docs tickets)",
    )
    g.add_argument(
        "--no-gemini",
        dest="with_gemini",
        action="store_false",
        help="skip the Gemini Flash extractor row (no per-ticket Gemini cost)",
    )
    args = p.parse_args()

    if args.make_labels:
        try:
            written = write_label_template()
            print(
                f"[eval] wrote {written}-row label template -> {LABELS_PATH}\n"
                "  Fill in faithful/useful (1-5) for each row, then run `make eval`."
            )
        except FileExistsError as e:
            print(f"[eval] {e}")
    else:
        run(extraction_only=args.extraction_only, with_gemini=args.with_gemini)
