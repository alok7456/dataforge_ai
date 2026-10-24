import argparse
import os
import sys
import json
import hashlib
from datetime import date

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv(
    "DW_URL", "postgresql+psycopg2://orderflow:orderflow123@localhost:5433/orderflow_dw"
)
STAGING, REJECTED, REPORTS = "data/staging", "data/rejected", "reports"
TODAY = date.today()


# ---------------- helpers ----------------
def md5_row(values):
    s = "|".join("" if pd.isna(v) else str(v) for v in values)
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def records(df):
    """DataFrame -> list of dicts with python-native values and NaN -> None."""
    return df.astype(object).where(df.notna(), None).to_dict("records")


def read_staging(name):
    return pd.read_csv(f"{STAGING}/{name}_valid.csv", dtype=str)


def date_key_series(series):
    dt = pd.to_datetime(series, errors="coerce")
    vals = [None if pd.isna(x) else int(x.strftime("%Y%m%d")) for x in dt]
    return pd.Series(vals, index=series.index, dtype=object)


def int_or_none(series):
    vals = [None if pd.isna(x) else int(x) for x in series]
    return pd.Series(vals, index=series.index, dtype=object)


def classify(rows, existing, key, hash_col="row_hash"):
    """CDC: split incoming rows into new / changed / unchanged by comparing hashes."""
    new, changed, same = [], [], 0
    for r in rows:
        old = existing.get(r[key])
        if old is None:
            new.append(r)
        elif old != r[hash_col]:
            changed.append(r)
        else:
            same += 1
    return new, changed, same


# ---------------- dimensions ----------------
def load_dim_date(conn):
    d = pd.DataFrame({"full_date": pd.date_range("2024-01-01", "2027-12-31")})
    fd = d["full_date"]
    d["date_key"] = fd.dt.strftime("%Y%m%d").astype(int)
    d["day"] = fd.dt.day
    d["month"] = fd.dt.month
    d["month_name"] = fd.dt.strftime("%B")
    d["quarter"] = fd.dt.quarter
    d["year"] = fd.dt.year
    d["day_name"] = fd.dt.strftime("%A")
    d["is_weekend"] = fd.dt.dayofweek >= 5
    d["full_date"] = fd.dt.strftime("%Y-%m-%d")
    conn.execute(text("""
        INSERT INTO dw.dim_date (date_key, full_date, day, month, month_name, quarter, year, day_name, is_weekend)
        VALUES (:date_key, :full_date, :day, :month, :month_name, :quarter, :year, :day_name, :is_weekend)
        ON CONFLICT (date_key) DO NOTHING"""), records(d))


def load_dim_product(conn, orders):
    prods = pd.DataFrame({"product_id": sorted(orders["PRODUCT_ID"].unique())})
    existing = {r[0] for r in conn.execute(text("SELECT product_id FROM dw.dim_product"))}
    new = prods[~prods["product_id"].isin(existing)]
    if len(new):
        conn.execute(text("INSERT INTO dw.dim_product (product_id) VALUES (:product_id)"), records(new))
    return dict(total=len(prods), inserted=len(new), updated=0, unchanged=len(prods) - len(new))


def load_dim_courier(conn, df):
    """SCD Type 1: overwrite changed attributes."""
    df = df.copy()
    df["SLA_DAYS"] = df["SLA_DAYS"].astype(int)
    cols = ["COURIER_NAME", "SLA_DAYS", "SERVICE_TYPE"]
    df["row_hash"] = [md5_row(r) for r in df[cols].itertuples(index=False)]
    rows = records(df[["COURIER_ID"] + cols + ["row_hash"]])
    existing = {r[0]: r[1] for r in conn.execute(text("SELECT courier_id, row_hash FROM dw.dim_courier"))}
    new, changed, same = classify(rows, existing, "COURIER_ID")
    if new:
        conn.execute(text("""
            INSERT INTO dw.dim_courier (courier_id, courier_name, sla_days, service_type, row_hash)
            VALUES (:COURIER_ID, :COURIER_NAME, :SLA_DAYS, :SERVICE_TYPE, :row_hash)"""), new)
    if changed:
        conn.execute(text("""
            UPDATE dw.dim_courier SET courier_name=:COURIER_NAME, sla_days=:SLA_DAYS,
                   service_type=:SERVICE_TYPE, row_hash=:row_hash, updated_at=now()
            WHERE courier_id=:COURIER_ID"""), changed)
    return dict(total=len(rows), inserted=len(new), updated=len(changed), unchanged=same)


def load_dim_customer(conn, df):
    """SCD Type 2: close the old version, insert a new one when attributes change."""
    df = df.copy()
    cols = ["CUSTOMER_NAME", "CITY", "STATE", "CUSTOMER_SEGMENT"]
    df["row_hash"] = [md5_row(r) for r in df[cols].itertuples(index=False)]
    rows = records(df[["CUSTOMER_ID"] + cols + ["CREATED_AT", "row_hash"]])
    existing = {r[0]: r[1] for r in conn.execute(
        text("SELECT customer_id, row_hash FROM dw.dim_customer WHERE is_current"))}
    new, changed, same = classify(rows, existing, "CUSTOMER_ID")
    if changed:
        conn.execute(text("""
            UPDATE dw.dim_customer SET end_date=:today, is_current=FALSE
            WHERE customer_id=:CUSTOMER_ID AND is_current"""),
            [{"today": TODAY, "CUSTOMER_ID": r["CUSTOMER_ID"]} for r in changed])
    to_insert = [{**r, "start_date": r["CREATED_AT"] or TODAY} for r in new] + \
                [{**r, "start_date": TODAY} for r in changed]
    if to_insert:
        conn.execute(text("""
            INSERT INTO dw.dim_customer
              (customer_id, customer_name, city, state, customer_segment, created_at, row_hash, start_date)
            VALUES (:CUSTOMER_ID, :CUSTOMER_NAME, :CITY, :STATE, :CUSTOMER_SEGMENT, :CREATED_AT, :row_hash, :start_date)
        """), to_insert)
    return dict(total=len(rows), inserted=len(new), updated=len(changed), unchanged=same)


# ---------------- fact ----------------
FACT_COLS = [
    "order_id", "customer_key", "product_key", "courier_key",
    "order_date_key", "shipped_date_key", "delivery_date_key",
    "order_status", "payment_status", "sales_channel",
    "quantity", "unit_price", "order_amount",
    "delivery_days", "sla_days", "delay_days",
    "delivered_flag", "on_time_flag", "late_delivery_flag",
    "cancelled_flag", "returned_flag", "in_transit_flag",
    "source_dataset", "row_hash", "last_updated_at",
]
INT_COLS = ["customer_key", "product_key", "courier_key", "quantity", "sla_days"]


def load_fact(conn, orders):
    cust = {r[0]: r[1] for r in conn.execute(
        text("SELECT customer_id, customer_key FROM dw.dim_customer WHERE is_current"))}
    prod = {r[0]: r[1] for r in conn.execute(text("SELECT product_id, product_key FROM dw.dim_product"))}
    cour = {r[0]: (r[1], r[2]) for r in conn.execute(
        text("SELECT courier_id, courier_key, sla_days FROM dw.dim_courier"))}

    f = orders.copy()
    hash_cols = ["ORDER_ID", "CUSTOMER_ID", "PRODUCT_ID", "COURIER_ID", "ORDER_DATE", "SHIPPED_DATE",
                 "DELIVERY_DATE", "ORDER_STATUS", "QUANTITY", "UNIT_PRICE", "PAYMENT_STATUS",
                 "SALES_CHANNEL", "LAST_UPDATED_AT"]
    f["row_hash"] = [md5_row(r) for r in f[hash_cols].itertuples(index=False)]

    s = pd.to_datetime(f["SHIPPED_DATE"])
    d = pd.to_datetime(f["DELIVERY_DATE"])
    qty = f["QUANTITY"].astype(int)
    price = f["UNIT_PRICE"].astype(float)
    status = f["ORDER_STATUS"]
    sla = f["COURIER_ID"].map(lambda c: cour.get(c, (None, None))[1])
    delivered = status == "Delivered"
    days = (d - s).dt.days

    out = pd.DataFrame({
        "order_id": f["ORDER_ID"],
        "customer_key": f["CUSTOMER_ID"].map(cust),
        "product_key": f["PRODUCT_ID"].map(prod),
        "courier_key": f["COURIER_ID"].map(lambda c: cour.get(c, (None, None))[0]),
        "order_date_key": date_key_series(f["ORDER_DATE"]),
        "shipped_date_key": date_key_series(f["SHIPPED_DATE"]),
        "delivery_date_key": date_key_series(f["DELIVERY_DATE"]),
        "order_status": status,
        "payment_status": f["PAYMENT_STATUS"],
        "sales_channel": f["SALES_CHANNEL"],
        "quantity": qty,
        "unit_price": price,
        "order_amount": (qty * price).round(2),
        "delivery_days": int_or_none(days.where(delivered)),
        "sla_days": sla,
        "delay_days": int_or_none((days - sla).clip(lower=0).where(delivered)),
        "delivered_flag": delivered,
        "on_time_flag": delivered & (days <= sla),
        "late_delivery_flag": delivered & (days > sla),
        "cancelled_flag": status == "Cancelled",
        "returned_flag": status == "Returned",
        "in_transit_flag": status == "In Transit",
        "source_dataset": f["source_dataset"],
        "row_hash": f["row_hash"],
        "last_updated_at": f["LAST_UPDATED_AT"],
    })

    missing = out[["customer_key", "product_key", "courier_key"]].isna().any(axis=1).sum()
    if missing:
        raise ValueError(f"{missing} order rows could not resolve a surrogate key")

    rows = records(out)
    for r in rows:
        for c in INT_COLS:
            if r[c] is not None:
                r[c] = int(r[c])

    existing = {r[0]: r[1] for r in conn.execute(
        text("SELECT order_id, row_hash FROM dw.fact_order_fulfillment"))}
    new, changed, same = classify(rows, existing, "order_id")

    cols = ", ".join(FACT_COLS)
    vals = ", ".join(f":{c}" for c in FACT_COLS)
    sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in FACT_COLS if c != "order_id")
    sql = text(f"INSERT INTO dw.fact_order_fulfillment ({cols}) VALUES ({vals}) "
               f"ON CONFLICT (order_id) DO UPDATE SET {sets}, loaded_at=now()")
    todo = new + changed
    if todo:
        conn.execute(sql, todo)
    return dict(total=len(rows), inserted=len(new), updated=len(changed), unchanged=same)


# ---------------- rejected records + audit ----------------
def load_rejected(conn):
    conn.execute(text("TRUNCATE dw.rejected_records RESTART IDENTITY"))
    rows = []
    for name in ["customers", "couriers", "orders_clean", "orders_dirty"]:
        df = pd.read_csv(f"{REJECTED}/{name}_rejected.csv", dtype=str)
        for r in records(df):
            rows.append({"dataset": name, "source_row": int(r["SOURCE_ROW"]),
                         "reject_reason": r["REJECT_REASON"], "raw_record": json.dumps(r)})
    if rows:
        conn.execute(text("""
            INSERT INTO dw.rejected_records (dataset, source_row, reject_reason, raw_record)
            VALUES (:dataset, :source_row, :reject_reason, CAST(:raw_record AS JSONB))"""), rows)
    return len(rows)


def write_audit(conn, dataset, source_rows, valid_rows, rejected_rows, st, status="SUCCESS"):
    conn.execute(text("""
        INSERT INTO dw.etl_audit (dataset, source_rows, valid_rows, rejected_rows,
                                  inserted_rows, updated_rows, unchanged_rows, run_status)
        VALUES (:d, :s, :v, :r, :i, :u, :n, :st)"""),
        dict(d=dataset, s=source_rows, v=valid_rows, r=rejected_rows,
             i=(st or {}).get("inserted"), u=(st or {}).get("updated"),
             n=(st or {}).get("unchanged"), st=status))


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["all", "dims", "facts"], default="all",
                    help="dims = date/courier/customer; facts = product/fact/rejected")
    part = ap.parse_args().part

    engine = create_engine(DB_URL)
    recon = pd.read_csv(f"{REPORTS}/reconciliation.csv").set_index("dataset")

    customers = read_staging("customers")
    couriers = read_staging("couriers")
    orders = pd.concat(
        [read_staging("orders_clean").assign(source_dataset="orders_clean"),
         read_staging("orders_dirty").assign(source_dataset="orders_dirty")],
        ignore_index=True)

    stats, n_rejected = {}, None
    try:
        with engine.begin() as conn:      # one transaction: all-or-nothing
            if part in ("all", "dims"):
                load_dim_date(conn)
                stats["dim_courier"] = load_dim_courier(conn, couriers)
                stats["dim_customer"] = load_dim_customer(conn, customers)
            if part in ("all", "facts"):
                stats["dim_product"] = load_dim_product(conn, orders)
                stats["fact_order_fulfillment"] = load_fact(conn, orders)
                n_rejected = load_rejected(conn)

            o = recon.loc[["orders_clean", "orders_dirty"]]
            for name, st in stats.items():
                if name == "dim_customer":
                    r = recon.loc["customers"]
                elif name == "dim_courier":
                    r = recon.loc["couriers"]
                elif name == "fact_order_fulfillment":
                    r = o.sum()
                else:
                    r = None
                if r is None:
                    write_audit(conn, name, st["total"], st["total"], 0, st)
                else:
                    write_audit(conn, name, int(r["source_rows"]), int(r["valid_rows"]),
                                int(r["rejected_rows"]), st)
    except Exception as e:
        print(f"\nLOAD FAILED (rolled back): {e}")
        with engine.begin() as conn:
            write_audit(conn, "load_warehouse", None, None, None, None, status="FAILED")
        sys.exit(1)

    print(f"\n=== LOAD SUMMARY (part={part}) ===")
    print(pd.DataFrame(stats).T.to_string())
    if n_rejected is not None:
        print(f"\nrejected_records loaded: {n_rejected}")


if __name__ == "__main__":
    main()