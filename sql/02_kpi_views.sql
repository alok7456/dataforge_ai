-- Order metrics
CREATE OR REPLACE VIEW dw.kpi_order_summary AS
SELECT
    count(*)                                AS total_orders,
    count(*) FILTER (WHERE delivered_flag)  AS delivered_orders,
    count(*) FILTER (WHERE cancelled_flag)  AS cancelled_orders,
    count(*) FILTER (WHERE returned_flag)   AS returned_orders,
    count(*) FILTER (WHERE in_transit_flag) AS in_transit_orders
FROM dw.fact_order_fulfillment;

-- Customer metrics (joined to dim_customer so SCD2 history never double-counts a customer)
CREATE OR REPLACE VIEW dw.kpi_customer_summary AS
SELECT count(DISTINCT c.customer_id) AS distinct_customers
FROM dw.fact_order_fulfillment f
JOIN dw.dim_customer c ON c.customer_key = f.customer_key;

CREATE OR REPLACE VIEW dw.kpi_top10_customers AS
SELECT c.customer_id,
       max(c.customer_name) AS customer_name,
       count(*)             AS total_orders
FROM dw.fact_order_fulfillment f
JOIN dw.dim_customer c ON c.customer_key = f.customer_key
GROUP BY c.customer_id
ORDER BY total_orders DESC, c.customer_id
LIMIT 10;

-- Fulfillment metrics
CREATE OR REPLACE VIEW dw.kpi_fulfillment_summary AS
SELECT
    round(avg(delivery_days) FILTER (WHERE delivered_flag), 2) AS avg_delivery_days,
    round(avg(sla_days), 2)                                    AS avg_sla_days,
    round(100.0 * count(*) FILTER (WHERE on_time_flag)
          / NULLIF(count(*) FILTER (WHERE delivered_flag), 0), 2)        AS on_time_delivery_pct,
    round(100.0 * count(*) FILTER (WHERE late_delivery_flag)
          / NULLIF(count(*) FILTER (WHERE delivered_flag), 0), 2)        AS late_delivery_pct,
    round(100.0 * count(*) FILTER (WHERE delivered_flag)
          / NULLIF(count(*) FILTER (WHERE delivered_flag OR returned_flag OR cancelled_flag), 0), 2)
                                                                         AS shipment_success_rate_pct
FROM dw.fact_order_fulfillment;

-- Courier metrics
CREATE OR REPLACE VIEW dw.kpi_courier_performance AS
SELECT
    cr.courier_id,
    cr.courier_name,
    cr.sla_days,
    count(f.order_id)                                   AS total_orders,
    count(*) FILTER (WHERE f.delivered_flag)            AS delivered_orders,
    round(100.0 * count(*) FILTER (WHERE f.on_time_flag)
          / NULLIF(count(*) FILTER (WHERE f.delivered_flag), 0), 2)       AS on_time_pct,
    round(100.0 * count(*) FILTER (WHERE f.late_delivery_flag)
          / NULLIF(count(*) FILTER (WHERE f.delivered_flag), 0), 2)       AS delay_pct,
    round(avg(f.delivery_days) FILTER (WHERE f.delivered_flag), 2)        AS avg_delivery_days,
    round(avg(f.delay_days)    FILTER (WHERE f.delivered_flag), 2)        AS avg_delay_days
FROM dw.dim_courier cr
LEFT JOIN dw.fact_order_fulfillment f ON f.courier_key = cr.courier_key
GROUP BY cr.courier_id, cr.courier_name, cr.sla_days
ORDER BY cr.courier_id;

CREATE OR REPLACE VIEW dw.kpi_courier_best_worst AS
(SELECT 'Best'::text AS ranking, p.*
   FROM dw.kpi_courier_performance p
  WHERE p.delivered_orders > 0
  ORDER BY p.on_time_pct DESC, p.delivered_orders DESC, p.courier_id
  LIMIT 1)
UNION ALL
(SELECT 'Worst'::text, p.*
   FROM dw.kpi_courier_performance p
  WHERE p.delivered_orders > 0
  ORDER BY p.on_time_pct ASC, p.delivered_orders DESC, p.courier_id
  LIMIT 1);

-- Trend metrics
CREATE OR REPLACE VIEW dw.kpi_monthly_order_trend AS
SELECT to_char(d.full_date, 'YYYY-MM') AS year_month, count(*) AS total_orders
FROM dw.fact_order_fulfillment f
JOIN dw.dim_date d ON d.date_key = f.order_date_key
GROUP BY 1 ORDER BY 1;

CREATE OR REPLACE VIEW dw.kpi_monthly_delivery_trend AS
SELECT to_char(d.full_date, 'YYYY-MM') AS year_month, count(*) AS delivered_orders
FROM dw.fact_order_fulfillment f
JOIN dw.dim_date d ON d.date_key = f.delivery_date_key
WHERE f.delivered_flag
GROUP BY 1 ORDER BY 1;

CREATE OR REPLACE VIEW dw.kpi_status_trend AS
SELECT to_char(d.full_date, 'YYYY-MM') AS year_month, f.order_status, count(*) AS total_orders
FROM dw.fact_order_fulfillment f
JOIN dw.dim_date d ON d.date_key = f.order_date_key
GROUP BY 1, 2 ORDER BY 1, 2;

CREATE OR REPLACE VIEW dw.kpi_courier_trend AS
SELECT to_char(d.full_date, 'YYYY-MM') AS year_month,
       cr.courier_id, cr.courier_name, count(*) AS total_orders
FROM dw.fact_order_fulfillment f
JOIN dw.dim_date d    ON d.date_key = f.order_date_key
JOIN dw.dim_courier cr ON cr.courier_key = f.courier_key
GROUP BY 1, 2, 3 ORDER BY 1, 2;