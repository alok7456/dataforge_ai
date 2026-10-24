import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv(
    "DW_URL", "postgresql+psycopg2://orderflow:orderflow123@localhost:5433/orderflow_dw"
)
SRC, STAGING, REJECTED, REPORTS = "data/source", "data/staging", "data/rejected", "reports"
SOURCE_FILES = {
    "customers": "customer_master_orders_v3.csv",
    "couriers": "courier_sla_master_v3.csv",
    "orders_clean": "order_transactions_v3.csv",
    "orders_dirty": "order_transactions_dirty_v3.csv",
}
checks = []


def add(name, expected, actual):
    checks.append({"check": name, "expected": expected, "actual": actual,
                   "result": "PASS" if expected == actual else "FAIL"})


def n_rows(path):
    return len(pd.read_csv(path, dtype=str))


def main():
    os.makedirs(REPORTS, exist_ok=True)
    engine = create_engine(DB_URL)

    # 1. file level: nothing lost between source and (valid + rejected)
    valid = {}
    for name, fname in SOURCE_FILES.items():
        src = n_rows(f"{SRC}/{fname}")
        ok = n_rows(f"{STAGING}/{name}_valid.csv")
        rej = n_rows(f"{REJECTED}/{name}_rejected.csv")
        valid[name] = ok
        add(f"{name}: source rows = valid + rejected", src, ok + rej)

    orders = pd.concat([pd.read_csv(f"{STAGING}/orders_clean_valid.csv", dtype=str),
                        pd.read_csv(f"{STAGING}/orders_dirty_valid.csv", dtype=str)])
    cour = pd.read_csv(f"{STAGING}/couriers_valid.csv", dtype=str)
    cour["SLA_DAYS"] = cour["SLA_DAYS"].astype(int)
    o = orders.merge(cour[["COURIER_ID", "SLA_DAYS"]], on="COURIER_ID", how="left")
    delivered = o["ORDER_STATUS"] == "Delivered"
    days = (pd.to_datetime(o["DELIVERY_DATE"]) - pd.to_datetime(o["SHIPPED_DATE"])).dt.days

    with engine.connect() as conn:
        def scalar(sql):
            return conn.execute(text(sql)).scalar()

        # 2. staging -> warehouse
        fact_n = scalar("SELECT count(*) FROM dw.fact_order_fulfillment")
        add("fact rows = valid clean + valid dirty orders",
            valid["orders_clean"] + valid["orders_dirty"], fact_n)
        add("dim_customer current rows = valid customers", valid["customers"],
            scalar("SELECT count(*) FROM dw.dim_customer WHERE is_current"))
        add("dim_courier rows = valid couriers", valid["couriers"],
            scalar("SELECT count(*) FROM dw.dim_courier"))
        total_rej = sum(n_rows(f"{REJECTED}/{n}_rejected.csv") for n in SOURCE_FILES)
        add("rejected_records table = rejected files", total_rej,
            scalar("SELECT count(*) FROM dw.rejected_records"))

        # 3. model integrity
        add("fact grain: distinct order_id = row count", fact_n,
            scalar("SELECT count(DISTINCT order_id) FROM dw.fact_order_fulfillment"))
        add("customers with more than one current version", 0, scalar(
            "SELECT count(*) FROM (SELECT customer_id FROM dw.dim_customer "
            "WHERE is_current GROUP BY 1 HAVING count(*) > 1) x"))
        add("delivered orders missing delivery_days", 0, scalar(
            "SELECT count(*) FROM dw.fact_order_fulfillment "
            "WHERE delivered_flag AND delivery_days IS NULL"))
        add("on-time + late = delivered",
            scalar("SELECT count(*) FROM dw.fact_order_fulfillment WHERE delivered_flag"),
            scalar("SELECT count(*) FROM dw.fact_order_fulfillment "
                   "WHERE on_time_flag OR late_delivery_flag"))

        # 4. independent recompute from staging files vs warehouse flags
        for status, col in [("Delivered", "delivered_flag"), ("Cancelled", "cancelled_flag"),
                            ("Returned", "returned_flag"), ("In Transit", "in_transit_flag")]:
            add(f"{status} orders: staging recompute vs warehouse",
                int((o["ORDER_STATUS"] == status).sum()),
                scalar(f"SELECT count(*) FROM dw.fact_order_fulfillment WHERE {col}"))
        add("on-time orders: staging recompute vs warehouse",
            int((delivered & (days <= o["SLA_DAYS"])).sum()),
            scalar("SELECT count(*) FROM dw.fact_order_fulfillment WHERE on_time_flag"))
        add("late orders: staging recompute vs warehouse",
            int((delivered & (days > o["SLA_DAYS"])).sum()),
            scalar("SELECT count(*) FROM dw.fact_order_fulfillment WHERE late_delivery_flag"))

        # 5. KPI layer = fact layer
        add("kpi_order_summary.total_orders = fact rows", fact_n,
            scalar("SELECT total_orders FROM dw.kpi_order_summary"))

    df = pd.DataFrame(checks)
    df.to_csv(f"{REPORTS}/reconciliation_report.csv", index=False)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 70)
    print("\n=== RECONCILIATION REPORT ===")
    print(df.to_string(index=False))
    failed = int((df["result"] == "FAIL").sum())
    print(f"\n{len(df) - failed}/{len(df)} checks passed.", "ALL GOOD" if not failed else "REVIEW THE FAIL ROWS")
    print(f"Saved: {REPORTS}/reconciliation_report.csv")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()