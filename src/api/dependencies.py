"""
dependencies.py
---------------
FastAPI dependency injection functions.

Using dependency injection means:
  - The database connection is created once and reused
  - The agent is initialised once at startup (expensive LLM init)
  - Tests can swap these out easily by overriding dependencies
  - Endpoints stay clean — they just declare what they need
"""

import logging
import os
import sqlite3
from pathlib import Path
from typing import Generator

from fastapi import Depends, HTTPException

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "ecommerce.db"

# ── Agent is a singleton — initialised once at startup ────
# Stored at module level so it's shared across all requests.
# Initialising per-request would be slow and wasteful.
_agent_instance = None


def get_agent():
    """
    Return the singleton agent instance.
    Raises 503 if agent has not been initialised yet.
    """
    global _agent_instance
    if _agent_instance is None:
        raise HTTPException(
            status_code=503,
            detail="Agent not initialised. Check ANTHROPIC_API_KEY is set.",
        )
    return _agent_instance


def init_agent():
    """
    Initialise the agent singleton at application startup.
    Called from the FastAPI lifespan event.
    Returns True if successful, False if API key is missing.
    """
    global _agent_instance
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set — agent will not be available")
        return False
    try:
        from src.agent.agent import TextToSQLAgent
        _agent_instance = TextToSQLAgent(
            model="claude-haiku-4-5-20251001",
            temperature=0.0,
        )
        logger.info("Agent initialised successfully")
        return True
    except Exception as e:
        logger.error(f"Agent initialisation failed: {e}")
        return False


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    FastAPI dependency that yields a SQLite connection.
    The connection is closed automatically after the request
    finishes — even if an exception is raised.

    Usage in an endpoint:
        def my_endpoint(conn: sqlite3.Connection = Depends(get_db)):
            ...
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()