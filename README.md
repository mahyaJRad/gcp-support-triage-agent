# Support-Triage Agent

A prototype that triages incoming technical support tickets on Google Cloud. For
a new ticket it extracts the entities and sentiment, retrieves historically
similar *resolved* tickets, and drafts a grounded "likely fix" summary that cites
the tickets it relied on. The capabilities are exposed as modular tools behind an
agent that decides how to chain them.

Stack Overflow questions stand in for a support queue: title = subject, body =
issue, tags = category, accepted answer = resolution. The public
`bigquery-public-data.stackoverflow` dataset is already hosted in BigQuery, and
its tags double as a multi-label gold standard for evaluating extraction.

## Architecture

```
ticket -> extract_entities (NL API) -> find_related_tickets (BigQuery) -> summarize (Gemini) -> brief
                                                  agent orchestration loop (ADK)
```

| Capability | GCP service | Rationale | ADR |
|------------|-------------|-----------|-----|
| Corpus storage | BigQuery | Dataset already hosted there; serverless SQL; free query tier | [0001](docs/adr/0001-dataset-choice.md) |
| Entities + sentiment | Cloud Natural Language API | Managed, deterministic, entity-level sentiment, free tier | [0002](docs/adr/0002-nl-api-vs-llm-extraction.md) |
| Retrieval | BigQuery (SQL tag overlap; optional GQL property graph) | Relationship-shaped data; no extra service | [0003](docs/adr/0003-graph-vs-vector-retrieval.md) |
| Summarization | Gemini Flash on Vertex AI | GCP-native generation, low cost, sufficient quality | [0004](docs/adr/0004-cost-and-model-selection.md) |
| Orchestration | Agent Development Kit (ADK) | First-party, code-first tools, local dev | [0006](docs/adr/0006-adk-orchestration.md) |

Diagrams and component details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Design decisions: [docs/adr/](docs/adr/). Roadmap and productionization:
[docs/ROADMAP.md](docs/ROADMAP.md).

## Setup

Requirements: macOS/Linux, [conda](https://github.com/conda-forge/miniforge), the
`gcloud` CLI, and a GCP project with billing enabled. The environment pins
**Python 3.11** because the GCP/ADK/spaCy stack does not yet ship wheels for 3.12+.

```bash
# tooling (macOS / Homebrew)
brew install --cask miniforge google-cloud-sdk

# python environment (creates the `support-triage` conda env + spaCy model)
make env
conda activate support-triage

# configuration
cp .env.example .env          # set GCP_PROJECT_ID and region

# authentication and APIs
gcloud auth login
gcloud auth application-default login
gcloud config set project "$GCP_PROJECT_ID"
gcloud services enable bigquery.googleapis.com aiplatform.googleapis.com language.googleapis.com
```

The SDKs use Application Default Credentials, so no key files live in the repo.
The BigQuery working dataset is created in the `US` multi-region to match the
public source.

## Usage

```bash
python -m support_triage.data.ingest --dry-run   # estimate bytes; runs nothing
make ingest        # sample the public corpus into your BigQuery dataset
make eda           # corpus statistics (+ plots saved under notebooks/figures/)
make notebook      # open notebooks/01_eda.ipynb in JupyterLab
make extract       # NL API entity + sentiment extraction
make summarize     # Gemini Flash summaries
make eval          # entity/tag overlap metric + summary spot-check
make run-agent     # launch the ADK agent locally (adk web)
make test          # offline tests (no GCP credentials needed)
```

## Dependencies

`requirements.txt` is the source of truth (loosely pinned direct deps).
`environment.yml` pins Python 3.11 and installs it via pip. `requirements-lock.txt`
is a full `pip freeze` for exact rebuilds.

After editing `requirements.txt`, re-sync the active env and refresh the lock:

```bash
make env-update                          # or: pip install -r requirements.txt
pip freeze > requirements-lock.txt       # regenerate the exact-rebuild lock
```

The EDA notebook (`notebooks/01_eda.ipynb`) needs the `matplotlib` + `jupyterlab`
extras; run `make env-update` once after pulling these changes, then `make notebook`.

## Project layout

```
src/support_triage/   data, extraction, summarization, graph (retrieval), agent, eval
sql/                  corpus sampling, property-graph DDL, retrieval traversals
docs/                 architecture, ADRs, roadmap
notebooks/            EDA
tests/                offline tests
```

## Cost

Designed to run at roughly zero cost: BigQuery's 1 TB/month free query tier, the
NL API's 5,000 free units/month, and Gemini Flash (cents at this volume). Sample
sizes are capped in `config.py` and every paid path supports a dry run. See
[ADR 0004](docs/adr/0004-cost-and-model-selection.md).
