# E-Commerce Analytics Agent

## Live Demo

API is deployed at: https://ecommerce-analytics-agent.onrender.com

- Interactive docs: https://ecommerce-analytics-agent.onrender.com/docs
- Health check: https://ecommerce-analytics-agent.onrender.com/health

An end-to-end AI-powered analytics pipeline for a fictional e-commerce company. Raw, messy data is ingested, cleaned, loaded into a normalized SQLite database, and exposed through a LangChain Text-to-SQL agent and FastAPI REST API.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        RAW DATA LAYER                           │
│  orders_raw.csv  customers_raw.json  products_raw.csv           │
│  reviews_raw.csv                                                │
│  ~1,770 total rows with intentional data quality issues         │
└────────────────────────────┬────────────────────────────────────┘
                             │ pandas read_csv / json.load
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      CLEANING LAYER  (src/ingestion/)           │
│  loader.py   → loads raw files into DataFrames                  │
│  cleaner.py  → fixes dates, prices, duplicates, nulls, HTML     │
│  profiler.py → generates before/after data quality reports      │
│  validator.py→ 28 programmatic assertions post-clean            │
│                                                                 │
│  Technology: Python 3.13, pandas 3.0, BeautifulSoup4           │
└────────────────────────────┬────────────────────────────────────┘
                             │ clean DataFrames
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DATABASE LAYER  (src/database/)            │
│  schema.sql  → DDL: 4 tables, PKs, FKs, CHECK constraints      │
│  loader.py   → parameterized INSERT with NaN→NULL conversion    │
│  verifier.py → post-load row counts + FK integrity checks       │
│                                                                 │
│  Schema (Star):  orders (fact) ──→ customers (dim)              │
│                  orders (fact) ──→ products  (dim)              │
│                  reviews       ──→ products  (dim)              │
│                                                                 │
│  Technology: SQLite 3, Python sqlite3                           │
└────────────────────────────┬────────────────────────────────────┘
                             │ SQL queries
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       AGENT LAYER  (src/agent/)                 │
│  prompts.py → schema context + SQL generation + retry prompts   │
│  agent.py   → LangChain Text-to-SQL with safety + retry logic   │
│                                                                 │
│  Flow: Question → Generate SQL → Safety check → Execute         │
│                              ↓ (on error)                       │
│                          Retry with error context → Execute     │
│                              ↓                                  │
│                          Format plain-English answer            │
│                                                                 │
│  Technology: LangChain, Anthropic Claude (claude-haiku-4-5)     │
└────────────────────────────┬────────────────────────────────────┘
                             │ JSON responses
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        API LAYER  (src/api/)                    │
│  main.py         → FastAPI app, CORS, middleware, error handlers│
│  models.py       → Pydantic schemas for all endpoints           │
│  dependencies.py → DB connection + agent singleton injection    │
│  routes/         → one file per endpoint group                  │
│                                                                 │
│  Technology: FastAPI, Pydantic v2, Uvicorn                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ecommerce_project/
├── data/
│   ├── raw/                        # Original messy input files
│   │   ├── orders_raw.csv
│   │   ├── customers_raw.json
│   │   ├── products_raw.csv
│   │   └── reviews_raw.csv
│   └── processed/                  # Cleaned CSVs + profile reports
├── logs/                           # Pipeline and agent run logs
├── src/
│   ├── ingestion/
│   │   ├── loader.py               # Load raw files
│   │   ├── cleaner.py              # Clean all 4 datasets
│   │   ├── profiler.py             # Data quality reports
│   │   └── validator.py            # Post-clean assertions
│   ├── database/
│   │   ├── schema.sql              # DDL — CREATE TABLE statements
│   │   ├── loader.py               # Load cleaned data into SQLite
│   │   └── verifier.py             # Post-load integrity checks
│   ├── agent/
│   │   ├── prompts.py              # All LLM prompt templates
│   │   └── agent.py                # Text-to-SQL agent
│   └── api/
│       ├── main.py                 # FastAPI app entry point
│       ├── models.py               # Pydantic request/response schemas
│       ├── dependencies.py         # DB + agent dependency injection
│       └── routes/
│           ├── health.py           # GET /health
│           ├── etl.py              # POST /etl/run, GET /etl/status
│           ├── query.py            # POST /query, GET /query/history
│           └── analytics.py        # GET /analytics/summary
├── tests/
│   ├── test_cleaner.py             # Unit tests for cleaning functions
│   ├── test_api.py                 # FastAPI endpoint tests
│   └── test_validator.py           # SQL safety validator tests
├── ecommerce.db                    # SQLite database (auto-created)
├── run_pipeline.py                 # Step 1: Run full cleaning pipeline
├── run_db.py                       # Step 2: Load data into SQLite
├── analytics.py                    # Step 3: Pandas analytics
├── queries.sql                     # Step 4: Hand-written SQL queries
├── run_agent.py                    # Step 5: Run agent on test questions
├── agent_evaluation.json           # Agent vs expected SQL comparison
└── requirements.txt
```

---

## Setup Instructions

### Requirements
- Python 3.10 or higher
- An Anthropic API key (get one at console.anthropic.com)

### 1 — Clone and enter the project

```bash
cd /Users/yourname/your-folder/ecommerce_project
```

### 2 — Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate          # Mac/Linux
venv\Scripts\activate             # Windows
```

### 3 — Install dependencies

```bash
pip install -r requirements.txt
```

If `requirements.txt` is not present, install manually:

```bash
pip install pandas beautifulsoup4 lxml sqlalchemy \
            langchain langchain-anthropic langchain-community \
            fastapi uvicorn pydantic pytest httpx
```

### 4 — Add raw data files

Place these 4 files in `data/raw/`:
```
data/raw/orders_raw.csv
data/raw/customers_raw.json
data/raw/products_raw.csv
data/raw/reviews_raw.csv
```

### 5 — Set environment variable

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

To make this permanent across terminal sessions:
```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
source ~/.zshrc
```

### 6 — Run the full pipeline

```bash
# Step 1: Clean raw data
python run_pipeline.py

# Step 2: Load into SQLite
python run_db.py

# Step 3: Pandas analytics
python analytics.py

# Step 5: Run agent on all 10 test questions
python run_agent.py
```

### 7 — Start the API

```bash
uvicorn src.api.main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for the interactive API documentation.

### 8 — Run tests

```bash
pytest tests/ -v
```

---

## API Documentation

Base URL: `http://localhost:8000`

Interactive docs: `http://localhost:8000/docs`

### GET /health

Returns database connectivity status, row counts per table, and agent readiness.

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "ok",
  "database": "connected",
  "agent_ready": true,
  "table_counts": [
    {"table": "customers", "rows": 200},
    {"table": "products",  "rows": 46},
    {"table": "orders",    "rows": 919},
    {"table": "reviews",   "rows": 455}
  ],
  "timestamp": "2024-12-31T15:00:00Z"
}
```

---

### POST /etl/run

Triggers the full ETL pipeline (ingest → clean → load) as a background job.

```bash
curl -X POST http://localhost:8000/etl/run \
  -H "Content-Type: application/json" \
  -d '{"force_reload": false}'
```

Response:
```json
{
  "job_id": "etl_20241231_150000_abc123",
  "status": "queued",
  "message": "ETL pipeline started in background",
  "started_at": "2024-12-31T15:00:00Z"
}
```

### GET /etl/status/{job_id}

Poll the status of a background ETL job.

```bash
curl http://localhost:8000/etl/status/etl_20241231_150000_abc123
```

---

### POST /query

Accepts a natural language question and returns the agent's answer with generated SQL.

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the top 5 products by total revenue?"}'
```

Response:
```json
{
  "question": "What are the top 5 products by total revenue?",
  "answer": "The top 5 products by total revenue are...",
  "sql_generated": "SELECT p.product_name, ...",
  "raw_result": [...],
  "execution_time_ms": 842.3,
  "retried": false,
  "row_count": 5
}
```

---

### GET /query/history

Returns the last N queries with pagination.

```bash
curl "http://localhost:8000/query/history?limit=10&offset=0"
```

---

### GET /analytics/summary

Returns pre-computed analytics via direct SQL (does not use the agent).

```bash
curl http://localhost:8000/analytics/summary
```

---

### POST /query/validate

Checks whether a SQL string is safe to execute. Does not execute it.

```bash
curl -X POST http://localhost:8000/query/validate \
  -H "Content-Type: application/json" \
  -d '{"sql": "DROP TABLE orders"}'
```

Response:
```json
{
  "sql": "DROP TABLE orders",
  "is_safe": false,
  "reason": "Blocked keyword detected: 'DROP'"
}
```

---

## Design Decisions

### Why a star schema instead of snowflake?

The data naturally splits into one fact table (`orders`) and two dimension tables (`customers`, `products`). A snowflake schema would further normalize dimensions — for example splitting `customers` into `customers` + `cities` + `countries`. For a dataset of 200 customers this adds joins without any storage benefit. Star schema means simpler queries, which also helps the LangChain agent generate correct SQL more reliably.

### Why TEXT for dates in SQLite?

SQLite has no native DATE type — it stores everything internally as TEXT, INTEGER, or REAL. Storing dates as ISO-format TEXT (`YYYY-MM-DD`) is the recommended SQLite pattern because ISO strings sort correctly lexicographically, comparisons work naturally (`order_date > '2024-01-01'`), and `strftime()` parses them reliably. Using INTEGER (Unix timestamps) would make the schema harder to read and the agent's SQL harder to generate correctly.

### Why inject schema into the prompt instead of using SQLDatabaseChain?

LangChain's `SQLDatabaseChain` uses introspection to retrieve schema dynamically at query time. For a 4-table database with a known schema, this adds latency and unpredictability — the introspection output varies and may not include the relationship context, column notes (e.g. "booleans stored as 0/1"), or date format notes the LLM needs. Injecting a carefully crafted schema block into every system message gives the LLM complete, consistent context and produces more reliable SQL.

### Why a single retry cycle instead of multiple?

Most SQL failures fall into two categories: wrong column name (fixed by seeing the error) and wrong table join (fixed by seeing the error). A second retry rarely succeeds if the first retry failed — it usually indicates a fundamentally ambiguous question. Adding more retries increases API cost and latency without proportional accuracy improvement.

### Why dtype=str when loading CSVs?

Loading with `dtype=str` preserves messy raw values exactly — `"AED 58.37"` stays as the string `"AED 58.37"` rather than causing a parse error or being silently coerced. Cleaning then happens explicitly in `cleaner.py` where every transformation is documented and logged.

---

## Challenges and Solutions

### Challenge 1 — Ambiguous date formats (DD/MM vs MM/DD)

The orders and customers datasets contained six different date formats mixed together, including `07/01/2024` which is ambiguous between July 1st and January 7th. Since the dataset covers a Middle Eastern / international customer base, DD/MM was the dominant convention. The solution was to try format strings in priority order: ISO (`YYYY-MM-DD`) first as it is unambiguous, then `DD/MM/YYYY`, then `MM/DD/YYYY` as a fallback, then abbreviated month names, then full month names, then pandas inference as a last resort. This order encodes the domain assumption without hardcoding a single format.

### Challenge 2 — Orphaned foreign keys across tables

After cleaning each dataset individually, orders still referenced customer IDs (`CUST-9xxx`) and product IDs that did not exist in the cleaned tables. Individual cleaners couldn't catch this because each cleaner only sees one DataFrame. The solution was a cross-dataset validation step at the end of `clean_all()` — after all four tables were individually cleaned, valid ID sets were built from customers and products, and orders/reviews were filtered against them. This required running customers and products cleaning before orders and reviews.

### Challenge 3 — SQLite's PRAGMA foreign_keys is session-scoped

SQLite does not enforce foreign key constraints by default — `PRAGMA foreign_keys = ON` must be run for every new connection. During the database loading phase this was missed on the first attempt, causing orphaned rows to insert silently. The solution was to centralise connection creation in `_get_connection()` which always executes the PRAGMA immediately after opening, making it impossible to get a connection without FK enforcement. The FastAPI `get_db()` dependency does the same.

---

## Data Quality Summary

| Table | Raw Rows | Clean Rows | Issues Fixed |
|---|---|---|---|
| orders | 1,020 | 919 | Duplicates, mixed dates, currency symbols, null FKs, orphaned refs |
| customers | 203 | 200 | Duplicates, nested JSON, mixed date formats, is_active type mix |
| products | 51 | 46 | Duplicates, HTML tags, negative prices, missing categories |
| reviews | 500 | 455 | Duplicate IDs, 33 rating formats, 10 verified_purchase formats |