import os
import pandas as pd
from sqlalchemy import create_engine

DB_URL = os.getenv(
    "DW_URL", "postgresql+psycopg2://orderflow:orderflow123@localhost:5433/orderflow_dw"
)
OUT = "reports/kpi_outputs"
os.makedirs(OUT, exist_ok=True)

VIEWS = [
    "kpi_order_summary", "kpi_customer_summary", "kpi_top10_customers",
    "kpi_fulfillment_summary", "kpi_courier_performance", "kpi_courier_best_worst",
    "kpi_monthly_order_trend", "kpi_monthly_delivery_trend",
    "kpi_status_trend", "kpi_courier_trend",
]

engine = create_engine(DB_URL)
for v in VIEWS:
    df = pd.read_sql(f"SELECT * FROM dw.{v}", engine)
    df.to_csv(f"{OUT}/{v}.csv", index=False)
    print(f"\n=== {v} ({len(df)} rows) ===")
    print(df.head(15).to_string(index=False))
    if len(df) > 15:
        print(f"... first 15 of {len(df)} rows shown, full file saved")
print(f"\nSaved CSVs to {OUT}/")