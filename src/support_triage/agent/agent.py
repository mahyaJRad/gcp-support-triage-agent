"""The Support-Triage ADK agent. Run locally: `adk web src/support_triage/agent`.

Orchestration rationale: docs/adr/0006-adk-orchestration.md.
"""

from __future__ import annotations

from support_triage.agent.tools import (
    extract_entities,
    find_related_tickets,
    summarize_ticket,
)
from support_triage.config import CONFIG

INSTRUCTION = (
    "You triage technical support tickets. Treat the user's message AS the "
    "incoming ticket text - do not ask them to paste a ticket. Always run this "
    "workflow by calling the tools: (1) call extract_entities on the message to "
    "pull the core issue and entities; (2) call find_related_tickets on the same "
    "message to retrieve related RESOLVED tickets; (3) ground your answer ONLY in "
    "those retrieved tickets, and cite every ticket id and url you used. If no "
    "related resolved ticket comes back, say so plainly and suggest an escalation "
    "path. Never invent a fix or a ticket id. Only ask a clarifying question if "
    "the message contains no technical content at all."
)


def build_agent():
    """Construct the root ADK agent with the three Phase-1 tools."""
    from google.adk.agents import Agent  # imported lazily so tests don't need ADK

    return Agent(
        name="support_triage_agent",
        model=CONFIG.gemini_model,
        instruction=INSTRUCTION,
        tools=[extract_entities, find_related_tickets, summarize_ticket],
    )


# ADK's `adk web` / `adk run` looks for a module-level `root_agent`.
root_agent = build_agent()
