"""Structure smoke tests - run WITHOUT GCP credentials (mock the clients).
Lets a reviewer validate the scaffold without a project. `pytest -q`.
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


def test_agent_tools_have_descriptions():
    # ADK uses the docstring as the tool description - it must exist and be useful
    from support_triage.agent.tools import (
        extract_entities,
        find_related_tickets,
        summarize_ticket,
    )

    for tool in (extract_entities, find_related_tickets, summarize_ticket):
        assert tool.__doc__ and len(tool.__doc__) > 40
