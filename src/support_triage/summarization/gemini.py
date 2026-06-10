"""Gemini Flash summarization via Vertex AI."""

from __future__ import annotations

from functools import lru_cache

from support_triage.config import CONFIG

GROUNDED_PROMPT = (
    "Summarize the following support ticket in ONE short paragraph of at most "
    "3 sentences (about 60 words). Keep it brief so the whole summary fits well "
    "within the response token limit and is never cut off mid-sentence. Use only "
    "information present in the ticket; if the resolution is unknown, say so. Do "
    "not invent fixes.\n\nTICKET:\n{ticket}\n"
)


def _trim_to_last_sentence(text: str) -> str:
    """Drop a trailing partial sentence so we never store a mid-clause fragment.

    Safety net for the rare ticket whose thinking tokens exhaust the output
    budget (finish_reason=MAX_TOKENS). If no sentence-ending punctuation is
    present at all, return the text unchanged rather than emptying it.
    """
    if not text or text[-1] in ".!?":
        return text
    cut = max(text.rfind(c) for c in ".!?")
    return text[: cut + 1].rstrip() if cut != -1 else text


@lru_cache(maxsize=1)
def _model():
    """Initialize Vertex AI and build the Flash model once per process."""
    import vertexai
    from vertexai.generative_models import GenerativeModel

    vertexai.init(project=CONFIG.project_id, location=CONFIG.vertex_location)
    return GenerativeModel(CONFIG.gemini_model)


def summarize(text: str) -> str:
    """Return a grounded one-paragraph summary using Gemini Flash (temp 0.2)."""
    from vertexai.generative_models import GenerationConfig

    from support_triage.gcp import with_backoff

    # gemini-2.5-flash is a "thinking" model: reasoning tokens draw from the same
    # output budget, so a too-small cap truncates the answer mid-sentence. Typical
    # thinking is ~200-315 tokens but a few complex tickets spike toward ~1k, so we
    # give a generous cap; the prompt keeps the *answer* short and cheap, and
    # _trim_to_last_sentence guarantees clean output if a spike still truncates.
    resp = with_backoff(
        _model().generate_content,
        GROUNDED_PROMPT.format(ticket=text),
        generation_config=GenerationConfig(temperature=0.2, max_output_tokens=1536),
    )
    return _trim_to_last_sentence((resp.text or "").strip())


def summarize_cluster(related: list[dict]) -> str:
    """Synthesize several resolved tickets into one 'known issue and likely fix'
    brief that cites the source ticket ids."""
    raise NotImplementedError
