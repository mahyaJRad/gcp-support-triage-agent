"""Text preprocessing: strip HTML from SO bodies, truncate for API limits."""

from __future__ import annotations

from bs4 import BeautifulSoup


def clean_html(raw: str) -> str:
    """Strip HTML tags/code blocks from a Stack Overflow body into plain text."""
    return BeautifulSoup(raw or "", "lxml").get_text(separator=" ", strip=True)


def truncate(text: str, max_chars: int = 1000) -> str:
    """Cap length to control NL API units / Gemini tokens (1 unit ~= 1000 chars)."""
    return text[:max_chars]
