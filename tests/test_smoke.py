"""Structure smoke tests - run WITHOUT GCP credentials (mock the clients).
"""

from support_triage.config import CONFIG
from support_triage.data.ingest import render_sql
from support_triage.data.preprocess import clean_html, truncate
from support_triage.summarization.gemini import GROUNDED_PROMPT


def test_config_loads():
    assert CONFIG.gemini_model.startswith("gemini")
    assert CONFIG.sample_rows > 0
    assert CONFIG.max_docs <= 5000  # free-tier guardrail
    assert CONFIG.bq_location == "US"  # must colocate with the public dataset


def test_clean_html_strips_tags():
    assert clean_html("<p>hello <code>x=1</code></p>") == "hello x=1"


def test_truncate_caps_length():
    assert len(truncate("a" * 5000, max_chars=1000)) == 1000


def test_prompt_is_grounded():
    # the summarization prompt must forbid inventing fixes
    assert "do not invent" in GROUNDED_PROMPT.lower()


def test_render_sql_substitutes_placeholders():
    sql = render_sql()
    # all template placeholders must be resolved before hitting BigQuery
    for placeholder in ("@DATASET", "@TAG", "@ROWS", "@PERCENT"):
        assert placeholder not in sql
    assert CONFIG.sample_tag in sql
    assert "TABLESAMPLE SYSTEM" in sql  # cost guardrail must be present
    assert "bigquery-public-data.stackoverflow" in sql


def test_retrieval_tokenizer():
    from support_triage.graph.queries import _terms

    toks = _terms("BigQuery error: cannot query cross-region dataset!")
    assert "bigquery" in toks and "cross-region" in toks
    assert all(len(t) >= 2 for t in toks)  # no single-char noise


def test_spacy_baseline_matches_nl_api_schema():
    # the spaCy baseline must emit the SAME keys as the NL API path so the two
    # extractors can be scored with the identical eval metric
    from support_triage.extraction.baseline_spacy import extract_spacy

    ents = extract_spacy("Google Cloud Storage upload fails in San Francisco.")
    assert isinstance(ents, list) and ents, "expected at least one entity"
    expected = {"name", "type", "salience", "entity_sentiment_score", "entity_sentiment_magnitude"}
    for e in ents:
        assert set(e) == expected
        assert e["entity_sentiment_score"] is None  # small model has no sentiment
    # salience is a normalised proxy: descending and summing to ~1
    saliences = [e["salience"] for e in ents]
    assert saliences == sorted(saliences, reverse=True)
    assert abs(sum(saliences) - 1.0) < 0.01


def test_agent_tools_have_descriptions():
    # ADK uses the docstring as the tool description - it must exist and be useful
    from support_triage.agent.tools import (
        extract_entities,
        find_related_tickets,
        summarize_ticket,
    )

    for tool in (extract_entities, find_related_tickets, summarize_ticket):
        assert tool.__doc__ and len(tool.__doc__) > 40
