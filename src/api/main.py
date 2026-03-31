"""
main.py
-------
FastAPI application entry point.

Run with:
    uvicorn src.api.main:app --reload --port 8000

Then visit:
    http://localhost:8000/docs   ← interactive API docs
    http://localhost:8000/redoc  ← alternative docs
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.dependencies import init_agent
from src.api.models import ErrorResponse
from src.api.routes import health, etl, query, analytics

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)


# ─────────────────────────────────────────────────────────────
# LIFESPAN — startup and shutdown events
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup and once at shutdown.
    We initialise the agent here so it's ready before the
    first request arrives.
    """
    logger.info("Starting up — initialising agent...")
    agent_ok = init_agent()
    if agent_ok:
        logger.info("Agent ready")
    else:
        logger.warning("Agent not ready — ANTHROPIC_API_KEY may be missing")
    yield
    logger.info("Shutting down")


# ─────────────────────────────────────────────────────────────
# APP INSTANCE
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="E-Commerce Analytics API",
    description="""
Natural language analytics API for e-commerce data.

Ask questions in plain English and get SQL-powered answers from the database.

## Features
- **Natural language queries** via the LangChain Text-to-SQL agent
- **Pre-computed analytics** (revenue, top products, customer rankings)
- **ETL pipeline** trigger with background job tracking
- **SQL safety validation** — only SELECT queries are ever executed

## Data
The database contains cleaned and normalized e-commerce data:
- 200 customers, 46 products, 919 orders, 455 reviews
    """,
    version="1.0.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────
# MIDDLEWARE
# ─────────────────────────────────────────────────────────────

# CORS — allows the API to be called from a browser frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware — adds X-Process-Time header to every response
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    process_time_ms = round((time.time() - start) * 1000, 2)
    response.headers["X-Process-Time-Ms"] = str(process_time_ms)
    return response


# ─────────────────────────────────────────────────────────────
# EXCEPTION HANDLERS
# Returns consistent ErrorResponse shape for all errors
# ─────────────────────────────────────────────────────────────

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content=ErrorResponse(
            error="not_found",
            message=f"Endpoint {request.url.path} not found",
            status_code=404,
        ).model_dump(),
    )


@app.exception_handler(422)
async def validation_error_handler(request: Request, exc):
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="validation_error",
            message=str(exc),
            status_code=422,
        ).model_dump(),
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            message="An unexpected error occurred",
            status_code=500,
        ).model_dump(),
    )


# ─────────────────────────────────────────────────────────────
# ROUTERS
# Each router is defined in its own file under routes/
# ─────────────────────────────────────────────────────────────

app.include_router(health.router,    tags=["Health"])
app.include_router(etl.router,       tags=["ETL"],       prefix="")
app.include_router(query.router,     tags=["Query"],     prefix="")
app.include_router(analytics.router, tags=["Analytics"], prefix="")


# ─────────────────────────────────────────────────────────────
# ROOT
# ─────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return {
        "message": "E-Commerce Analytics API",
        "docs":    "/docs",
        "health":  "/health",
    }