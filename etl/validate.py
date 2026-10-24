import os
import pandas as pd

SRC = "data/source"
STAGING = "data/staging"
REJECTED = "data/rejected"
REPORTS = "reports"
for p in (STAGING, REJECTED, REPORTS):
    os.makedirs(p, exist_ok=True)

DATE_FORMAT = "%Y-%m-%d"
MAX_ORDER_DATE = pd.Timestamp("2026-09-22")   # orders after this are "future" -> rejected
VALID_STATUS = ["Delivered", "In Transit", "Cancelled", "Returned", "Shipped", "Processing"]


# ---------- helpers ----------
def read(filename):
    return pd.read_csv(os.path.join(SRC, filename), dtype=str)


def clean_strings(df):
    """Trim whitespace on every column; empty strings become null."""
    for c in df.columns:
        s = df[c].str.strip()
        df[c] = s.mask(s == "")
    df["SOURCE_ROW"] = df.index + 2   # CSV row number (header = row 1) for traceability
    return df


def collect_reasons(masks, index):
    """Combine boolean rule masks into one 'REASON1;REASON2' string per row."""
    flags = pd.DataFrame(masks, index=index)
    return flags.apply(lambda r: ";".join(flags.columns[r.values]), axis=1)


# ---------- customers ----------
def validate_customers(raw):
    df = clean_strings(raw.copy())
    created = pd.to_datetime(df["CREATED_AT"], format=DATE_FORMAT, errors="coerce")
    masks = {
        "NULL_CUSTOMER_ID": df["CUSTOMER_ID"].isna(),
        "INVALID_CREATED_AT": df["CREATED_AT"].notna() & created.isna(),
        "DUPLICATE_CUSTOMER_ID": df["CUSTOMER_ID"].notna() & df.duplicated("CUSTOMER_ID", keep="last"),
    }
    reasons = collect_reasons(masks, df.index)
    ok = reasons == ""
    valid = df[ok].copy()
    valid["CREATED_AT"] = created[ok].dt.strftime(DATE_FORMAT)
    rejected = df[~ok].copy()
    rejected["REJECT_REASON"] = reasons[~ok]
    return valid, rejected


# ---------- couriers ----------
def validate_couriers(raw):
    df = clean_strings(raw.copy())
    sla = pd.to_numeric(df["SLA_DAYS"], errors="coerce")
    masks = {
        "NULL_COURIER_ID": df["COURIER_ID"].isna(),
        "INVALID_SLA_DAYS": sla.isna() | (sla <= 0),
        "DUPLICATE_COURIER_ID": df["COURIER_ID"].notna() & df.duplicated("COURIER_ID", keep="last"),
    }
    reasons = collect_reasons(masks, df.index)
    ok = reasons == ""
    valid = df[ok].copy()
    valid["SLA_DAYS"] = sla[ok].astype(int)
    rejected = df[~ok].copy()
    rejected["REJECT_REASON"] = reasons[~ok]
    return valid, rejected


# ---------- orders ----------
def validate_orders(raw, customer_ids, courier_ids):
    df = clean_strings(raw.copy())

    o = pd.to_datetime(df["ORDER_DATE"], format=DATE_FORMAT, errors="coerce")
    s = pd.to_datetime(df["SHIPPED_DATE"], format=DATE_FORMAT, errors="coerce")
    d = pd.to_datetime(df["DELIVERY_DATE"], format=DATE_FORMAT, errors="coerce")
    qty = pd.to_numeric(df["QUANTITY"], errors="coerce")
    price = pd.to_numeric(df["UNIT_PRICE"], errors="coerce")

    # standardise status: trim + case-insensitive match to the canonical value
    status_map = {v.lower(): v for v in VALID_STATUS}
    status_std = df["ORDER_STATUS"].str.lower().map(status_map)

    masks = {
        # mandatory fields
        "NULL_ORDER_ID": df["ORDER_ID"].isna(),
        "NULL_CUSTOMER_ID": df["CUSTOMER_ID"].isna(),
        "NULL_PRODUCT_ID": df["PRODUCT_ID"].isna(),
        "NULL_COURIER_ID": df["COURIER_ID"].isna(),
        # dates
        "NULL_ORDER_DATE": df["ORDER_DATE"].isna(),
        "INVALID_ORDER_DATE": df["ORDER_DATE"].notna() & o.isna(),
        "INVALID_SHIPPED_DATE": df["SHIPPED_DATE"].notna() & s.isna(),
        "INVALID_DELIVERY_DATE": df["DELIVERY_DATE"].notna() & d.isna(),
        "FUTURE_ORDER_DATE": o > MAX_ORDER_DATE,
        # chronology
        "DELIVERY_BEFORE_SHIPPED": d < s,
        "DELIVERY_BEFORE_ORDER": d < o,
        "SHIPPED_BEFORE_ORDER": s < o,
        "DELIVERED_WITHOUT_DELIVERY_DATE": (status_std == "Delivered") & df["DELIVERY_DATE"].isna(),
        # quantity / price / status
        "NULL_OR_NON_NUMERIC_QUANTITY": qty.isna(),
        "NON_POSITIVE_QUANTITY": qty <= 0,
        "INVALID_UNIT_PRICE": price.isna() | (price <= 0),
        "INVALID_STATUS": status_std.isna(),
        # referential integrity
        "COURIER_NOT_IN_MASTER": df["COURIER_ID"].notna() & ~df["COURIER_ID"].isin(courier_ids),
        "CUSTOMER_NOT_IN_MASTER": df["CUSTOMER_ID"].notna() & ~df["CUSTOMER_ID"].isin(customer_ids),
    }
    reasons = collect_reasons(masks, df.index)

    # duplicates: among rows that passed every rule, keep the latest LAST_UPDATED_AT per ORDER_ID
    cand = df[reasons == ""].copy()
    cand["_upd"] = pd.to_datetime(cand["LAST_UPDATED_AT"], errors="coerce")
    cand = cand.sort_values(["ORDER_ID", "_upd"], na_position="first")
    older = cand.index[cand.duplicated("ORDER_ID", keep="last")]
    reasons.loc[older] = "DUPLICATE_ORDER_ID_OLDER_VERSION"

    ok = reasons == ""
    valid = df[ok].copy()
    valid["ORDER_DATE"] = o[ok].dt.strftime(DATE_FORMAT)
    valid["SHIPPED_DATE"] = s[ok].dt.strftime(DATE_FORMAT)
    valid["DELIVERY_DATE"] = d[ok].dt.strftime(DATE_FORMAT)
    valid["QUANTITY"] = qty[ok].astype(int)
    valid["UNIT_PRICE"] = price[ok]
    valid["ORDER_STATUS"] = status_std[ok]

    rejected = df[~ok].copy()
    rejected["REJECT_REASON"] = reasons[~ok]
    return valid, rejected


# ---------- run ----------
def main():
    cust_raw = read("customer_master_orders_v3.csv")
    cour_raw = read("courier_sla_master_v3.csv")
    cust_ok, cust_rej = validate_customers(cust_raw)
    cour_ok, cour_rej = validate_couriers(cour_raw)
    customer_ids = set(cust_ok["CUSTOMER_ID"])
    courier_ids = set(cour_ok["COURIER_ID"])

    results = {
        "customers": (len(cust_raw), cust_ok, cust_rej),
        "couriers": (len(cour_raw), cour_ok, cour_rej),
    }
    for name, fname in [("orders_clean", "order_transactions_v3.csv"),
                        ("orders_dirty", "order_transactions_dirty_v3.csv")]:
        raw = read(fname)
        ok, rej = validate_orders(raw, customer_ids, courier_ids)
        results[name] = (len(raw), ok, rej)

    recon, reason_rows = [], []
    for name, (n_src, ok, rej) in results.items():
        ok.to_csv(f"{STAGING}/{name}_valid.csv", index=False, encoding="utf-8")
        rej.to_csv(f"{REJECTED}/{name}_rejected.csv", index=False, encoding="utf-8")
        recon.append({
            "dataset": name,
            "source_rows": n_src,
            "valid_rows": len(ok),
            "rejected_rows": len(rej),
            "reconciliation": "PASS" if n_src == len(ok) + len(rej) else "FAIL",
        })
        if len(rej):
            counts = rej["REJECT_REASON"].str.split(";").explode().value_counts()
            for reason, c in counts.items():
                reason_rows.append({"dataset": name, "reason": reason, "rows": int(c)})

    recon_df = pd.DataFrame(recon)
    reasons_df = pd.DataFrame(reason_rows)
    recon_df.to_csv(f"{REPORTS}/reconciliation.csv", index=False)
    reasons_df.to_csv(f"{REPORTS}/reject_summary.csv", index=False)

    print("\n=== RECONCILIATION (source = valid + rejected) ===")
    print(recon_df.to_string(index=False))
    print("\n=== REJECT REASONS (a row with 2 problems counts under both) ===")
    print(reasons_df.to_string(index=False))
    print(f"\nValid files   -> {STAGING}/")
    print(f"Rejected files -> {REJECTED}/")


if __name__ == "__main__":
    main()