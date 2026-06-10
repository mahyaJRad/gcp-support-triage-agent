"""Agent tools: thin wrappers over the extraction, retrieval, and summarization
modules. The docstrings are the tool descriptions the model reads, so they state
what each tool does and when to use it.
"""

from __future__ import annotations

from support_triage.data.preprocess import truncate
from support_triage.extraction.nl_api import extract_text
from support_triage.graph.queries import find_related_by_text
from support_triage.summarization.gemini import summarize


def extract_entities(ticket_text: str) -> dict:
    """Extract the key entities and overall sentiment from a support ticket.
    Use this first to understand what a ticket is about. Returns
    {entities: [{name, type, salience}], sentiment: float}."""
    ex = extract_text(truncate(ticket_text))
    return {"entities": ex.entities, "sentiment": ex.sentiment_score}


def find_related_tickets(ticket_text: str, top_k: int = 5) -> list[dict]:
    """Find previously resolved tickets similar to this one by shared tags and
    entities. Use this to look for precedent before proposing a fix. Returns
    [{id, title, shared_tags, url}], or [] if nothing similar is resolved."""
    return find_related_by_text(ticket_text, top_k=top_k)


def summarize_ticket(ticket_text: str) -> str:
    """Produce a concise, grounded one-paragraph summary of a ticket. Use when the
    user wants a brief. Does not invent information not present in the ticket."""
    return summarize(ticket_text)
