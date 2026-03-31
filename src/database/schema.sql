-- =============================================================
-- schema.sql
-- Star schema for the e-commerce analytics database.
--
-- Table order matters — dimension tables first, fact tables last.
-- SQLite enforces FK constraints only when PRAGMA foreign_keys = ON
-- which is enabled at connection time in loader.py.
--
-- Design decisions:
--   • Star schema: orders is the fact table, customers/products are dimensions
--   • Dates stored as TEXT in ISO format (YYYY-MM-DD) — SQLite has no DATE type
--     but ISO strings sort and compare correctly
--   • Booleans stored as INTEGER (0/1) — SQLite has no BOOLEAN type
--   • All foreign key columns are NOT NULL — orphaned records break joins
--   • CHECK constraints mirror the validation rules from Phase 1
-- =============================================================


-- -------------------------------------------------------------
-- PRAGMA: enable foreign key enforcement
-- SQLite does not enforce FKs by default — this must be run
-- at the start of every connection that needs FK checks.
-- It is included here as documentation; loader.py sets it too.
-- -------------------------------------------------------------
PRAGMA foreign_keys = ON;


-- -------------------------------------------------------------
-- DIMENSION TABLE: customers
-- One row per unique customer.
-- No foreign keys — other tables point to this one.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    customer_id     TEXT        PRIMARY KEY,        -- e.g. CUST-1000
    first_name      TEXT        NOT NULL,
    last_name       TEXT        NOT NULL,
    email           TEXT,                           -- nullable: 4 customers have no email
    has_email       INTEGER     NOT NULL DEFAULT 0  -- 1=True, 0=False
                    CHECK (has_email IN (0, 1)),
    phone           TEXT,
    city            TEXT,
    country         TEXT,
    postal_code     TEXT,                           -- nullable: 3 customers missing
    signup_date     TEXT,                           -- ISO format: YYYY-MM-DD
    is_active       INTEGER     NOT NULL DEFAULT 1  -- 1=True, 0=False
                    CHECK (is_active IN (0, 1)),
    loyalty_tier    TEXT        NOT NULL DEFAULT 'none'
                    CHECK (loyalty_tier IN ('platinum','gold','silver','bronze','none'))
);

-- Index: frequently filtered columns in customer queries
CREATE INDEX IF NOT EXISTS idx_customers_city         ON customers (city);
CREATE INDEX IF NOT EXISTS idx_customers_country      ON customers (country);
CREATE INDEX IF NOT EXISTS idx_customers_loyalty_tier ON customers (loyalty_tier);
CREATE INDEX IF NOT EXISTS idx_customers_is_active    ON customers (is_active);


-- -------------------------------------------------------------
-- DIMENSION TABLE: products
-- One row per unique product (after deduplication).
-- No foreign keys — other tables point to this one.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    product_id      TEXT        PRIMARY KEY,        -- e.g. PROD-100
    sku             TEXT        NOT NULL UNIQUE,    -- stock keeping unit, must be unique
    product_name    TEXT        NOT NULL,
    category        TEXT        NOT NULL DEFAULT 'uncategorized',
    unit_price      REAL        NOT NULL
                    CHECK (unit_price > 0),         -- prices must be positive
    stock_quantity  INTEGER     NOT NULL DEFAULT 0
                    CHECK (stock_quantity >= 0),    -- stock can be 0 but not negative
    weight_kg       REAL,                           -- nullable: 2 products missing weight
    created_date    TEXT                            -- ISO format: YYYY-MM-DD
);

-- Index: most common filter/group-by columns for product queries
CREATE INDEX IF NOT EXISTS idx_products_category   ON products (category);
CREATE INDEX IF NOT EXISTS idx_products_unit_price ON products (unit_price);


-- -------------------------------------------------------------
-- FACT TABLE: orders
-- One row per order line.
-- References customers and products via foreign keys.
-- This is the central table in the star schema.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    order_id                TEXT    PRIMARY KEY,        -- e.g. ORD-10613
    customer_id             TEXT    NOT NULL
                            REFERENCES customers (customer_id),
    product_id              TEXT    NOT NULL
                            REFERENCES products (product_id),
    quantity                INTEGER NOT NULL
                            CHECK (quantity > 0),       -- must be positive
    unit_price              REAL    NOT NULL
                            CHECK (unit_price > 0),
    total_amount            REAL,                       -- nullable: 25 rows missing
    order_date              TEXT,                       -- ISO format: YYYY-MM-DD
    status                  TEXT    NOT NULL
                            CHECK (status IN (
                                'completed','shipped','processing',
                                'pending','returned','cancelled','delivered'
                            )),
    payment_method          TEXT,
    shipping_address_city   TEXT,                       -- nullable: 49 rows missing
    discount_pct            REAL    NOT NULL DEFAULT 0.0
                            CHECK (discount_pct >= 0)
);

-- Index: the most frequently queried columns in order analytics
-- customer_id and product_id — used in every join
-- order_date  — used in every time-based filter (monthly/quarterly reports)
-- status      — used in every "how many completed orders" type query
CREATE INDEX IF NOT EXISTS idx_orders_customer_id   ON orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_product_id    ON orders (product_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_date    ON orders (order_date);
CREATE INDEX IF NOT EXISTS idx_orders_status        ON orders (status);


-- -------------------------------------------------------------
-- FACT TABLE: reviews
-- One row per product review.
-- References products. Does not enforce customer FK because
-- a review's customer_id may not always map to a known customer
-- (reviews can exist for guests).
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reviews (
    review_id           TEXT    PRIMARY KEY,        -- e.g. REV-5000
    product_id          TEXT    NOT NULL
                        REFERENCES products (product_id),
    customer_id         TEXT    NOT NULL,           -- stored but not FK enforced
    rating              REAL
                        CHECK (rating IS NULL OR (rating >= 1.0 AND rating <= 5.0)),
    review_text         TEXT,                       -- nullable: 39 reviews have no text
    has_review_text     INTEGER NOT NULL DEFAULT 0
                        CHECK (has_review_text IN (0, 1)),
    review_date         TEXT,                       -- ISO format: YYYY-MM-DD
    verified_purchase   INTEGER                     -- 1=True, 0=False, NULL=unknown
                        CHECK (verified_purchase IS NULL OR verified_purchase IN (0, 1)),
    helpful_votes       INTEGER NOT NULL DEFAULT 0
                        CHECK (helpful_votes >= 0)
);

-- Index: most common review query patterns
CREATE INDEX IF NOT EXISTS idx_reviews_product_id   ON reviews (product_id);
CREATE INDEX IF NOT EXISTS idx_reviews_customer_id  ON reviews (customer_id);
CREATE INDEX IF NOT EXISTS idx_reviews_rating       ON reviews (rating);
