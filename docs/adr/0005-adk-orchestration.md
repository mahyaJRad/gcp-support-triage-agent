# ADR 0005 - Agent orchestration with ADK, run locally

## Status
Accepted

## Context
The extraction, retrieval, and summarization capabilities need to be orchestrated
as tools an agent can chain. The framework should be GCP-native and run locally
for development.

## Decision
Build the agent with Google's **Agent Development Kit (ADK)**; develop and demo
locally with `adk web` / `adk run`.

## Alternatives considered
- **LangChain / LlamaIndex:** capable, but not the first-party GCP path.
- **Agent Engine (managed runtime):** the production target, but it costs money
  and is unnecessary to demonstrate the design. Documented as a deployment step.

## Consequences
- (+) First-party GCP agent framework; tools map one-to-one to the `src` modules.
- (+) Local development is free; `adk deploy` is a one-command path to Agent
  Engine later.
- (+) Multi-agent composition and Memory Bank are native upgrades for the roadmap.
- (-) Pre-1.x ecosystem churn; the version is pinned in `requirements.txt`.
