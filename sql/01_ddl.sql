CREATE SCHEMA IF NOT EXISTS dw;

-- ============ DIMENSIONS ============
CREATE TABLE dw.dim_date (
    date_key     INT PRIMARY KEY,          -- 20250615
    full_date    DATE NOT NULL UNIQUE,
    day          SMALLINT NOT NULL,
    month        SMALLINT NOT NULL,
    month_name   VARCHAR(10) NOT NULL,
    quarter      SMALLINT NOT NULL,
    year         SMALLINT NOT NULL,
    day_name     VARCHAR(10) NOT NULL,
    is_weekend   BOOLEAN NOT NULL
);

-- SCD Type 2: history tracked with start/end dates
CREATE TABLE dw.dim_customer (
    customer_key     SERIAL PRIMARY KEY,
    customer_id      VARCHAR(20) NOT NULL,
    customer_name    VARCHAR(100),
    city             VARCHAR(60),
    state            VARCHAR(60),
    customer_segment VARCHAR(30),
    created_at       DATE,
    row_hash         CHAR(32) NOT NULL,
    start_date       DATE NOT NULL,
    end_date         DATE NOT NULL DEFAULT '9999-12-31',
    is_current       BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX uq_dim_customer_current
    ON dw.dim_customer (customer_id) WHERE is_current;

-- SCD Type 1: overwrite on change
CREATE TABLE dw.dim_courier (
    courier_key   SERIAL PRIMARY KEY,
    courier_id    VARCHAR(20) NOT NULL UNIQUE,
    courier_name  VARCHAR(60),
    sla_days      SMALLINT NOT NULL,
    service_type  VARCHAR(30),
    row_hash      CHAR(32) NOT NULL,
    updated_at    TIMESTAMP DEFAULT now()
);

-- Built from distinct valid product IDs in orders (no product master was supplied)
CREATE TABLE dw.dim_product (
    product_key  SERIAL PRIMARY KEY,
    product_id   VARCHAR(20) NOT NULL UNIQUE
);

-- ============ FACT (grain: one row per ORDER_ID) ============
CREATE TABLE dw.fact_order_fulfillment (
    order_id          VARCHAR(20) PRIMARY KEY,
    customer_key      INT NOT NULL REFERENCES dw.dim_customer(customer_key),
    product_key       INT NOT NULL REFERENCES dw.dim_product(product_key),
    courier_key       INT NOT NULL REFERENCES dw.dim_courier(courier_key),
    order_date_key    INT NOT NULL REFERENCES dw.dim_date(date_key),
    shipped_date_key  INT REFERENCES dw.dim_date(date_key),
    delivery_date_key INT REFERENCES dw.dim_date(date_key),
    order_status      VARCHAR(20) NOT NULL,
    payment_status    VARCHAR(20),
    sales_channel     VARCHAR(30),
    quantity          INT NOT NULL CHECK (quantity > 0),
    unit_price        NUMERIC(12,2),
    order_amount      NUMERIC(14,2),
    delivery_days     INT,
    sla_days          INT,
    delay_days        INT,
    delivered_flag    BOOLEAN NOT NULL,
    on_time_flag      BOOLEAN NOT NULL,
    late_delivery_flag BOOLEAN NOT NULL,
    cancelled_flag    BOOLEAN NOT NULL,
    returned_flag     BOOLEAN NOT NULL,
    in_transit_flag   BOOLEAN NOT NULL,
    source_dataset    VARCHAR(30),
    row_hash          CHAR(32),
    last_updated_at   TIMESTAMP,
    loaded_at         TIMESTAMP NOT NULL DEFAULT now()
);

-- ============ AUDIT / ERROR FRAMEWORK ============
CREATE TABLE dw.etl_audit (
    run_id         SERIAL PRIMARY KEY,
    dataset        VARCHAR(30) NOT NULL,
    source_rows    INT,
    valid_rows     INT,
    rejected_rows  INT,
    inserted_rows  INT,
    updated_rows   INT,
    unchanged_rows INT,
    run_status     VARCHAR(20),
    run_ts         TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE dw.rejected_records (
    reject_id     SERIAL PRIMARY KEY,
    dataset       VARCHAR(30),
    source_row    INT,
    reject_reason TEXT,
    raw_record    JSONB,
    loaded_at     TIMESTAMP NOT NULL DEFAULT now()
);