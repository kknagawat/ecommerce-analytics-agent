"""
models.py
---------
Pydantic schemas for all FastAPI request and response bodies.

Every field has a description and example so the auto-generated
/docs page is self-explanatory without reading source code.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# SHARED / UTILITY
# ─────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Consistent error shape returned for all 4xx and 5xx responses."""
    error:   str = Field(..., description="Short error type label",      example="validation_error")
    message: str = Field(..., description="Human-readable error detail", example="Question cannot be empty")
    status_code: int = Field(..., description="HTTP status code",        example=400)


# ─────────────────────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────────────────────

class TableCount(BaseModel):
    """Row count for a single database table."""
    table: str = Field(..., example="orders")
    rows:  int = Field(..., example=919)


class HealthResponse(BaseModel):
    """Response from GET /health."""
    status:        str              = Field(..., example="ok")
    database:      str              = Field(..., example="connected",
                                           description="'connected' or 'error'")
    agent_ready:   bool             = Field(..., example=True)
    table_counts:  list[TableCount] = Field(..., description="Row count per table")
    timestamp:     datetime         = Field(..., description="Server time at check")


# ─────────────────────────────────────────────────────────────
# POST /etl/run
# ─────────────────────────────────────────────────────────────

class ETLRequest(BaseModel):
    """Optional request body for POST /etl/run."""
    force_reload: bool = Field(
        default=False,
        description="If true, drops and recreates the database before loading",
        example=False,
    )


class ETLJobResponse(BaseModel):
    """Immediate response from POST /etl/run — job is running in background."""
    job_id:     str      = Field(..., description="Use this to poll /etl/status/{job_id}", example="etl_20240101_153045")
    status:     str      = Field(..., example="running")
    message:    str      = Field(..., example="ETL pipeline started in background")
    started_at: datetime = Field(..., description="When the job was triggered")


class ETLStatusResponse(BaseModel):
    """Response from GET /etl/status/{job_id}."""
    job_id:       str            = Field(..., example="etl_20240101_153045")
    status:       str            = Field(..., description="running | completed | failed", example="completed")
    started_at:   datetime       = Field(...)
    completed_at: Optional[datetime] = Field(None)
    duration_sec: Optional[float]    = Field(None, example=3.42)
    rows_loaded:  Optional[dict]     = Field(None, description="Row counts per table after load",
                                            example={"customers": 200, "products": 46, "orders": 919, "reviews": 455})
    errors:       list[str]          = Field(default_factory=list)
    message:      str                = Field(..., example="Pipeline completed successfully")


# ─────────────────────────────────────────────────────────────
# POST /query
# ─────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    """Request body for POST /query."""
    question: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Natural language question about the e-commerce data",
        example="What are the top 5 products by total revenue?",
    )


class QueryResponse(BaseModel):
    """Response from POST /query."""
    question:          str        = Field(..., example="What are the top 5 products by total revenue?")
    answer:            str        = Field(..., description="Plain-English answer from the agent")
    sql_generated:     str        = Field(..., description="The SQL query that was executed")
    raw_result:        list[dict] = Field(..., description="Raw rows returned by the SQL query")
    execution_time_ms: float      = Field(..., description="Total time from question to answer", example=842.3)
    retried:           bool       = Field(..., description="True if SQL needed correction after first failure")
    row_count:         int        = Field(..., description="Number of rows returned", example=5)


# ─────────────────────────────────────────────────────────────
# GET /query/history
# ─────────────────────────────────────────────────────────────

class QueryHistoryItem(BaseModel):
    """A single entry in the query history log."""
    id:                int       = Field(..., example=1)
    question:          str       = Field(..., example="What are the top 5 products?")
    sql_generated:     str       = Field(...)
    answer:            str       = Field(...)
    execution_time_ms: float     = Field(...)
    success:           bool      = Field(...)
    retried:           bool      = Field(...)
    row_count:         int       = Field(...)
    timestamp:         datetime  = Field(...)


class QueryHistoryResponse(BaseModel):
    """Response from GET /query/history."""
    items:  list[QueryHistoryItem] = Field(...)
    total:  int                    = Field(..., description="Total queries in history", example=42)
    limit:  int                    = Field(..., example=10)
    offset: int                    = Field(..., example=0)


# ─────────────────────────────────────────────────────────────
# GET /analytics/summary
# ─────────────────────────────────────────────────────────────

class TopProduct(BaseModel):
    product_id:    str   = Field(..., example="PROD-139")
    product_name:  str   = Field(..., example="Resistance Bands Set")
    category:      str   = Field(..., example="books")
    total_revenue: float = Field(..., example=21419.06)
    units_sold:    int   = Field(..., example=192)


class TopCustomer(BaseModel):
    customer_id:   str   = Field(..., example="CUST-1184")
    customer_name: str   = Field(..., example="Sara Miller")
    total_orders:  int   = Field(..., example=10)
    total_spent:   float = Field(..., example=8661.99)


class OrderStatusDist(BaseModel):
    status: str = Field(..., example="completed")
    count:  int = Field(..., example=212)
    pct:    float = Field(..., example=23.07)


class AnalyticsSummaryResponse(BaseModel):
    """Response from GET /analytics/summary."""
    total_revenue:          float                = Field(..., example=607104.62)
    total_orders:           int                  = Field(..., example=919)
    total_customers:        int                  = Field(..., example=200)
    total_products:         int                  = Field(..., example=46)
    avg_order_value:        float                = Field(..., example=659.85)
    top_5_products:         list[TopProduct]     = Field(...)
    top_5_customers:        list[TopCustomer]    = Field(...)
    order_status_dist:      list[OrderStatusDist]= Field(...)
    computed_at:            datetime             = Field(...)


# ─────────────────────────────────────────────────────────────
# POST /query/validate
# ─────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    """Request body for POST /query/validate."""
    sql: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="SQL query string to validate",
        example="SELECT * FROM orders LIMIT 5",
    )


class ValidateResponse(BaseModel):
    """Response from POST /query/validate."""
    sql:     str  = Field(..., description="The original SQL submitted")
    is_safe: bool = Field(..., description="True if query is a safe SELECT statement")
    reason:  str  = Field(..., description="Why the query is safe or blocked",
                          example="Query is a safe SELECT statement")