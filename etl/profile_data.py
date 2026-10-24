import os
import pandas as pd

SRC = "data/source"
OUT = "reports"
os.makedirs(OUT, exist_ok=True)

FILES = {
    "customers": "customer_master_orders_v3.csv",
    "orders_clean": "order_transactions_v3.csv",
    "orders_dirty": "order_transactions_dirty_v3.csv",
    "couriers": "courier_sla_master_v3.csv",
}
DATE_COLS = ["ORDER_DATE", "SHIPPED_DATE", "DELIVERY_DATE"]
VALID_STATUS = {"Delivered", "In Transit", "Cancelled", "Returned", "Shipped", "Processing"}
WINDOW_END = pd.Timestamp("2026-09-22")


def load(name):
    # dtype=str so bad dates / bad numbers are not silently converted
    return pd.read_csv(os.path.join(SRC, FILES[name]), dtype=str)


def column_profile(df, name):
    rows = []
    for c in df.columns:
        rows.append({
            "dataset": name,
            "column": c,
            "nulls": int(df[c].isna().sum()),
            "null_pct": round(df[c].isna().mean() * 100, 2),
            "distinct": int(df[c].nunique(dropna=True)),
        })
    return rows


def order_checks(df, name, customer_ids, courier_ids):
    res = []

    def add(check, count):
        res.append({"dataset": name, "check": check, "count": int(count)})

    add("record_count", len(df))
    add("null_order_id", df["ORDER_ID"].isna().sum())
    add("duplicate_order_id (extra rows)", df.duplicated("ORDER_ID", keep="first").sum())
    add("exact_duplicate_rows", df.duplicated(keep="first").sum())
    add("null_customer_id", df["CUSTOMER_ID"].isna().sum())
    add("null_product_id", df["PRODUCT_ID"].isna().sum())
    add("null_courier_id", df["COURIER_ID"].isna().sum())

    parsed = {}
    for c in DATE_COLS:
        p = pd.to_datetime(df[c].str.strip(), format="%Y-%m-%d", errors="coerce")
        parsed[c] = p
        add(f"null_{c}", df[c].isna().sum())
        add(f"invalid_date_{c}", (df[c].notna() & p.isna()).sum())

    q = pd.to_numeric(df["QUANTITY"], errors="coerce")
    add("null_quantity", df["QUANTITY"].isna().sum())
    add("non_numeric_quantity", (df["QUANTITY"].notna() & q.isna()).sum())
    add("zero_quantity", (q == 0).sum())
    add("negative_quantity", (q < 0).sum())

    o, s, d = parsed["ORDER_DATE"], parsed["SHIPPED_DATE"], parsed["DELIVERY_DATE"]
    add("delivery_before_shipped", (d < s).sum())
    add("delivery_before_order", (d < o).sum())
    add("shipped_before_order", (s < o).sum())
    add("future_order_date", (o > WINDOW_END).sum())

    st = df["ORDER_STATUS"]
    st_clean = st.str.strip()
    add("status_with_whitespace", (st.notna() & (st != st_clean)).sum())
    add("invalid_status", (st_clean.notna() & ~st_clean.isin(VALID_STATUS)).sum())
    add("delivered_missing_delivery_date",
        ((st_clean == "Delivered") & df["DELIVERY_DATE"].isna()).sum())

    add("courier_not_in_master",
        (df["COURIER_ID"].notna() & ~df["COURIER_ID"].isin(courier_ids)).sum())
    add("customer_not_in_master",
        (df["CUSTOMER_ID"].notna() & ~df["CUSTOMER_ID"].isin(customer_ids)).sum())
    return res


def main():
    data = {k: load(k) for k in FILES}
    customer_ids = set(data["customers"]["CUSTOMER_ID"].dropna())
    courier_ids = set(data["couriers"]["COURIER_ID"].dropna())

    col_rows, checks = [], []
    for name, df in data.items():
        col_rows += column_profile(df, name)

    checks.append({"dataset": "customers", "check": "record_count", "count": len(data["customers"])})
    checks.append({"dataset": "customers", "check": "duplicate_customer_id",
                   "count": int(data["customers"].duplicated("CUSTOMER_ID").sum())})
    checks.append({"dataset": "couriers", "check": "record_count", "count": len(data["couriers"])})
    checks.append({"dataset": "couriers", "check": "duplicate_courier_id",
                   "count": int(data["couriers"].duplicated("COURIER_ID").sum())})

    for name in ["orders_clean", "orders_dirty"]:
        checks += order_checks(data[name], name, customer_ids, courier_ids)

    col_df = pd.DataFrame(col_rows)
    chk_df = pd.DataFrame(checks)
    col_df.to_csv(os.path.join(OUT, "profile_columns.csv"), index=False, encoding="utf-8")
    chk_df.to_csv(os.path.join(OUT, "profile_checks.csv"), index=False, encoding="utf-8")

    # side-by-side view: clean vs dirty
    orders = chk_df[chk_df["dataset"].isin(["orders_clean", "orders_dirty"])]
    pivot = orders.pivot(index="check", columns="dataset", values="count")
    print("\n=== ORDER CHECKS: clean vs dirty ===")
    print(pivot.to_string())
    print("\n=== MASTER DATA CHECKS ===")
    print(chk_df[chk_df["dataset"].isin(["customers", "couriers"])].to_string(index=False))
    print("\n=== COLUMN PROFILE (orders_dirty) ===")
    print(col_df[col_df["dataset"] == "orders_dirty"].to_string(index=False))
    print(f"\nSaved: {OUT}/profile_checks.csv and {OUT}/profile_columns.csv")


if __name__ == "__main__":
    main()