# OrderFlow360 synthetic test data

## Files
- `customer_master_orders_v3.csv` — 300 customer master records.
- `order_transactions_v3.csv` — 2,500 mostly clean order transactions for baseline KPI and trend testing.
- `order_transactions_dirty_v3.csv` — 600 transactions, including deliberately injected data-quality problems.
- `courier_sla_master_v3.csv` — 12 courier/SLA master records.
- `expected_issue_manifest.csv` — row-number-based labels for deliberately injected dirty-record scenarios. Row numbers count the CSV header as row 1; it is test metadata, not an input to production ETL.

## Schema
`ORDER_ID, CUSTOMER_ID, PRODUCT_ID, COURIER_ID, ORDER_DATE, SHIPPED_DATE, DELIVERY_DATE, ORDER_STATUS, QUANTITY, UNIT_PRICE, PAYMENT_STATUS, SALES_CHANNEL, LAST_UPDATED_AT`

Customer master columns: `CUSTOMER_ID, CUSTOMER_NAME, CITY, STATE, CUSTOMER_SEGMENT, CREATED_AT`.
Courier SLA columns: `COURIER_ID, COURIER_NAME, SLA_DAYS, SERVICE_TYPE`.

## Injected dirty-data cases
Null customer/product/order/courier/date/quantity fields; unparseable and impossible dates (including `2026/13/40`); negative and zero quantities; delivery before shipped date; delivery before order date; shipment before order date; unknown courier/customer/product foreign keys; duplicate order IDs and exact duplicate rows; invalid status; whitespace-padded status; delivered order missing delivery date; future order date.

The core cases listed in the source brief are all represented: mandatory customer/product fields, invalid dates, negative/zero quantity, delivery chronology, courier missing from SLA master, and duplicate order IDs. Additional cases are included to exercise profiling, null analysis, foreign-key validation, standardization and quarantine logic.

## Important assumptions
- The brief does not define exact source column names beyond key business fields, so this package uses a documented, consistent schema suitable for ETL testing.
- `PRODUCT_ID` is included in transactions because the brief requires product validation and lists `DIM_PRODUCT`, but the brief does not specify a product master input file. Generate a product dimension from distinct valid transaction product IDs, or add a product master if your implementation requires one.
- Valid order statuses used in baseline data: `Delivered`, `In Transit`, `Cancelled`, `Returned`, `Shipped`, `Processing`. Dirty data includes an invalid status and whitespace-padded status.
- `DELIVERY_DATE` is blank for non-delivered statuses in many valid rows. Treat as expected for open/cancelled orders; a Delivered order without a delivery date is intentionally injected as dirty.
- Suggested date window is 2025-01-01 through 2026-09-22; future-date test records are intentional. The future-date issue is a recommended extra validation, not an explicit mandatory rule in the brief.
- Dirty file has 600 records and should be processed separately from the clean file to avoid accidental double-counting. For integrated testing, concatenate them only if you intentionally want to test cross-file duplicate handling.
- No actual customer personal information is used; records are synthetic.
- KPI definitions are marked “to be finalised” in the brief. Suggested conventions: on-time % = delivered orders delivered within courier SLA / delivered orders; late % = delivered orders beyond SLA / delivered orders; delivery days = delivery date - shipped date; delay days = max(delivery days - SLA days, 0); shipment success rate = delivered orders / (delivered + returned + cancelled), and document any alternative.
