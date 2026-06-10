# Thin wrappers so every pipeline step is reproducible 
.PHONY: env env-update setup ingest eda notebook build-graph extract summarize run-agent baseline eval lint test

env:             ## create the conda env (python 3.11 + pip deps) - run ONCE
	conda env create -f environment.yml
	conda run -n support-triage python -m spacy download en_core_web_sm
	@echo "Done. Activate with:  conda activate support-triage"

env-update:      ## re-sync the conda env after requirements.txt changes
	conda env update -f environment.yml --prune

setup:           ## install deps + spaCy model INTO the active env (pip-only path)
	pip install -r requirements.txt && python -m spacy download en_core_web_sm

ingest:          ## sample the public corpus into your BigQuery dataset
	python -m support_triage.data.ingest

eda:             ## run exploratory data analysis (script form; prints stats + saves plots)
	python -m support_triage.data.eda

notebook:        ## open the EDA notebook in JupyterLab (needs `make env-update` first)
	jupyter lab notebooks/01_eda.ipynb

build-graph:     ## create the BigQuery property graph (GQL DDL)
	python -m support_triage.graph.build

extract:         ## NL API entity + sentiment extraction
	python -m support_triage.extraction.run

summarize:       ## Gemini summaries
	python -m support_triage.summarization.run

run-agent:       ## launch the ADK agent locally
	adk web src/support_triage/agent

baseline:        ## traditional-NLP baseline: spaCy NER vs NL API (no Gemini cost)
	python -m support_triage.eval.run --extraction-only

eval:            ## evaluate extraction + summaries (incl. spaCy baseline comparison)
	python -m support_triage.eval.run

lint:
	ruff check src tests && ruff format --check src tests

test:
	pytest -q
