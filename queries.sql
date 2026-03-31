-- =============================================================
-- queries.sql
-- Hand-written analytical SQL queries against ecommerce.db
--
-- Each query includes:
--   • A comment explaining the approach
--   • Joins, CTEs, window functions where required
--   • Clean formatting for readability
-- =============================================================


-- =============================================================
-- Q1 — Top Revenue Products
-- Approach:
--   JOIN orders → products to attach category and product name.
--   GROUP BY product to compute total revenue, units sold, and
--   average order quantity per order line.
--   ORDER BY revenue DESC and LIMIT to top 10.
--   total_revenue uses SUM(o.total_amount) rather than
--   SUM(o.quantity * o.unit_price) because total_amount already
--   reflects any applied discounts.
-- =============================================================

SELECT
    p.product_id,
    p.product_name,
    p.category,
    SUM(o.quantity)                             AS total_units_sold,
    ROUND(SUM(o.total_amount), 2)               AS total_revenue,
    ROUND(AVG(o.quantity), 2)                   AS avg_order_quantity,
    COUNT(o.order_id)                           AS order_count
FROM orders  o
JOIN products p ON o.product_id = p.product_id
WHERE o.total_amount IS NOT NULL               -- exclude the 25 rows with no amount
GROUP BY
    p.product_id,
    p.product_name,
    p.category
ORDER BY total_revenue DESC
LIMIT 10;


-- =============================================================
-- Q2 — Monthly Revenue Trend (last 12 months)
-- Approach:
--   Use strftime('%Y-%m', order_date) to group by month.
--   LAG() window function looks back one row (ordered by month)
--   to get the previous month's revenue — used to compute MoM
--   growth as: (current - previous) / previous * 100.
--   NULLIF prevents division by zero if a prior month had 0 revenue.
--   The outer query filters to the last 12 distinct months.
-- =============================================================

WITH monthly_revenue AS (
    SELECT
        strftime('%Y-%m', order_date)           AS month,
        ROUND(SUM(total_amount), 2)             AS revenue
    FROM orders
    WHERE total_amount IS NOT NULL
      AND order_date   IS NOT NULL
    GROUP BY month
    ORDER BY month
),
with_lag AS (
    SELECT
        month,
        revenue,
        LAG(revenue) OVER (ORDER BY month)      AS prev_revenue
    FROM monthly_revenue
)
SELECT
    month,
    revenue,
    prev_revenue,
    ROUND(
        (revenue - prev_revenue)
        / NULLIF(prev_revenue, 0) * 100,
    2)                                          AS mom_growth_pct
FROM with_lag
ORDER BY month DESC
LIMIT 12;


-- =============================================================
-- Q3 — Customer Lifetime Value (top 20)
-- Approach:
--   Aggregate orders per customer to get total_orders,
--   total_spent, and avg_order_value.
--   DENSE_RANK() is used instead of RANK() so tied customers
--   share the same rank without gaps in the sequence.
--   JOIN customers to include name and loyalty tier for context.
--   HAVING total_orders > 0 is implicit but stated for clarity.
-- =============================================================

WITH customer_stats AS (
    SELECT
        o.customer_id,
        COUNT(o.order_id)                       AS total_orders,
        ROUND(SUM(o.total_amount), 2)           AS total_spent,
        ROUND(AVG(o.total_amount), 2)           AS avg_order_value
    FROM orders o
    WHERE o.total_amount IS NOT NULL
    GROUP BY o.customer_id
)
SELECT
    cs.customer_id,
    c.first_name || ' ' || c.last_name         AS customer_name,
    c.loyalty_tier,
    c.city,
    cs.total_orders,
    cs.total_spent,
    cs.avg_order_value,
    DENSE_RANK() OVER (
        ORDER BY cs.total_spent DESC
    )                                           AS spend_rank
FROM customer_stats cs
JOIN customers c ON cs.customer_id = c.customer_id
ORDER BY spend_rank
LIMIT 20;


-- =============================================================
-- Q4 — Category Revenue with Running Totals
-- Approach:
--   Step 1 (monthly_cat): aggregate revenue by category + month.
--   Step 2: apply SUM() OVER (PARTITION BY category ORDER BY month)
--   which restarts the running total for each category.
--   This gives a cumulative revenue view per category over time.
--   Results ordered by category then month for readability.
-- =============================================================

WITH monthly_cat AS (
    SELECT
        p.category,
        strftime('%Y-%m', o.order_date)         AS month,
        ROUND(SUM(o.total_amount), 2)           AS monthly_revenue
    FROM orders   o
    JOIN products p ON o.product_id = p.product_id
    WHERE o.total_amount IS NOT NULL
      AND o.order_date   IS NOT NULL
    GROUP BY
        p.category,
        month
)
SELECT
    category,
    month,
    monthly_revenue,
    ROUND(
        SUM(monthly_revenue) OVER (
            PARTITION BY category
            ORDER BY month
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ),
    2)                                          AS running_total
FROM monthly_cat
ORDER BY
    category,
    month;


-- =============================================================
-- Q5 — Review Sentiment vs Revenue Correlation
-- Approach:
--   CTE 1 (product_ratings): average rating per product from reviews.
--   CTE 2 (product_revenue): total revenue and units sold per product.
--   Final JOIN combines both with product details.
--   Only products that have BOTH reviews AND orders are included
--   (INNER JOIN) so the correlation is meaningful.
--   Ordered by avg_rating DESC to surface highest-rated products first.
-- =============================================================

WITH product_ratings AS (
    SELECT
        product_id,
        ROUND(AVG(rating), 2)                   AS avg_rating,
        COUNT(review_id)                        AS review_count
    FROM reviews
    WHERE rating IS NOT NULL
    GROUP BY product_id
),
product_revenue AS (
    SELECT
        product_id,
        ROUND(SUM(total_amount), 2)             AS total_revenue,
        SUM(quantity)                           AS total_units_sold,
        COUNT(order_id)                         AS order_count
    FROM orders
    WHERE total_amount IS NOT NULL
    GROUP BY product_id
)
SELECT
    p.product_id,
    p.product_name,
    p.category,
    pr.avg_rating,
    pr.review_count,
    rev.total_revenue,
    rev.total_units_sold,
    rev.order_count
FROM products       p
JOIN product_ratings  pr  ON p.product_id = pr.product_id
JOIN product_revenue  rev ON p.product_id = rev.product_id
ORDER BY pr.avg_rating DESC;


-- =============================================================
-- Q6 — Repeat Purchase Rate by Loyalty Tier
-- Approach:
--   CTE (order_counts): count orders per customer.
--   Main query joins with customers to get loyalty_tier.
--   For each tier:
--     • total_customers       = COUNT(DISTINCT customer_id)
--     • repeat_customers      = customers with more than 1 order
--     • repeat_purchase_rate  = repeat_customers / total_customers * 100
--   AVG(order_count) shows average orders per customer per tier.
--   NULLIF prevents division by zero for tiers with 0 customers.
-- =============================================================

WITH order_counts AS (
    SELECT
        customer_id,
        COUNT(order_id)                         AS order_count
    FROM orders
    GROUP BY customer_id
)
SELECT
    c.loyalty_tier,
    COUNT(oc.customer_id)                       AS total_customers,
    SUM(CASE WHEN oc.order_count > 1 THEN 1 ELSE 0 END)
                                                AS repeat_customers,
    ROUND(
        SUM(CASE WHEN oc.order_count > 1 THEN 1.0 ELSE 0 END)
        / NULLIF(COUNT(oc.customer_id), 0) * 100,
    2)                                          AS repeat_purchase_rate_pct,
    ROUND(AVG(oc.order_count), 2)               AS avg_orders_per_customer
FROM order_counts oc
JOIN customers    c  ON oc.customer_id = c.customer_id
GROUP BY c.loyalty_tier
ORDER BY repeat_purchase_rate_pct DESC;


-- =============================================================
-- Q7 — Inventory Turnover
-- Approach:
--   units_sold comes from SUM(quantity) in orders.
--   current_stock comes from products.stock_quantity.
--   turnover_ratio = units_sold / current_stock.
--   NULLIF(stock_quantity, 0) prevents division by zero for
--   out-of-stock products — those get NULL ratio.
--   CASE statement flags products as:
--     Fast Moving  — ratio > 5  (selling much faster than stocked)
--     Healthy      — ratio 0.5–5
--     Slow Moving  — ratio < 0.5 (stock far exceeds sales)
--     Out of Stock — stock is 0
--   LEFT JOIN ensures products with no orders still appear
--   (they would show 0 units sold and be flagged Slow Moving).
-- =============================================================

WITH product_sales AS (
    SELECT
        product_id,
        SUM(quantity)                           AS units_sold
    FROM orders
    GROUP BY product_id
)
SELECT
    p.product_id,
    p.product_name,
    p.category,
    p.stock_quantity                            AS current_stock,
    COALESCE(ps.units_sold, 0)                  AS units_sold,
    ROUND(
        COALESCE(ps.units_sold, 0)
        / NULLIF(CAST(p.stock_quantity AS REAL), 0),
    2)                                          AS turnover_ratio,
    CASE
        WHEN p.stock_quantity = 0
            THEN 'Out of Stock'
        WHEN COALESCE(ps.units_sold, 0)
             / NULLIF(CAST(p.stock_quantity AS REAL), 0) > 5
            THEN 'Fast Moving'
        WHEN COALESCE(ps.units_sold, 0)
             / NULLIF(CAST(p.stock_quantity AS REAL), 0) < 0.5
            THEN 'Slow Moving'
        ELSE 'Healthy'
    END                                         AS inventory_flag
FROM products    p
LEFT JOIN product_sales ps ON p.product_id = ps.product_id
ORDER BY turnover_ratio DESC NULLS LAST;
