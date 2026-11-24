# Retail NL2SQL Lab

A one-day workshop project that converts natural-language business questions into
auditable SQL using an LLM (Huawei Cloud MaaS, OpenAI-compatible API), with defensive
guardrails and a read-only DuckDB warehouse as the single source of truth.

**Core trust model:** the LLM only *proposes* SQL. Every statement is validated by
sqlglot-based guardrails (single SELECT, table allowlist, blocked functions), executed
read-only on DuckDB, and every question is logged to a JSONL audit trail. No numeric
result is trusted just because the model wrote it — DuckDB is the only source of numbers.

## Features

- Deterministic synthetic retail warehouse: 5 tables, 20,000 sale lines across 2026
  (`sales`, `stores`, `products`, `customers`, `suppliers`) with join-friendly keys
- SQL guardrails: single-statement enforcement, table/function allowlists,
  comment and semicolon rejection, 50-row output limit
- LLM proposal normalization (markdown fences, trailing semicolons) with rejected
  proposals recorded in the audit log
- Console (`src/app.py`) and Streamlit web UI (`src/webapp.py`) with sample questions,
  session history, and a Data catalog tab with per-table profiles and a refresh button
- Optional grounded answer summary that may only restate values DuckDB returned
- Mock mode (`MOCK_LLM=1`) that runs the entire pipeline offline with keyword templates

## Quickstart

```bash
python -m pip install -r requirements.txt
python -m src.setup_db          # builds retail.duckdb (deterministic seed)
python -m src.app              # console, mock mode by default
python -m streamlit run src/webapp.py   # web UI on localhost:8501
```

To use a real model, copy `.env.example` to `.env`, set `MAAS_BASE_URL`, `MAAS_MODEL`
and `MAAS_API_KEY` from your MaaS console, and set `MOCK_LLM=0`. Never commit `.env`.

## Tests

```bash
pytest -q
```

Covers guardrail rejections, warehouse counts and referential integrity, SQL
normalization, and the web UI flow (Streamlit AppTest).

## Documentation

See [RUNBOOK.md](RUNBOOK.md) for the full workshop manual: learning outcomes,
reference architecture, agenda, data model, guardrail exercises, evidence-based
interpretation rules, and production design discussion.

All data is fictional; amounts are in MXN.
