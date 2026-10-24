import os
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine

st.set_page_config(page_title="OrderFlow360 - Executive Dashboard", page_icon="📦", layout="wide")

DB_URL = os.getenv("DW_URL", "postgresql+psycopg2://orderflow:orderflow123@localhost:5433/orderflow_dw")


@st.cache_resource
def engine():
    return create_engine(DB_URL)


@st.cache_data(ttl=60)
def q(sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, engine())


def view(name):
    return q(f"SELECT * FROM dw.{name}")


# ---------- load ----------
try:
    orders = view("kpi_order_summary").iloc[0]
    cust = view("kpi_customer_summary").iloc[0]
    ful = view("kpi_fulfillment_summary").iloc[0]
    courier = view("kpi_courier_performance")
    best_worst = view("kpi_courier_best_worst")
    top10 = view("kpi_top10_customers")
    m_orders = view("kpi_monthly_order_trend")
    m_deliv = view("kpi_monthly_delivery_trend")
    status_trend = view("kpi_status_trend")
    courier_trend = view("kpi_courier_trend")
except Exception as e:
    st.error("Could not read KPI views. Has the pipeline loaded the warehouse yet?")
    st.code(str(e))
    st.stop()

if int(orders["total_orders"] or 0) == 0:
    st.warning("Warehouse is empty. Run the ETL / Airflow DAGs first, then refresh.")
    st.stop()

st.title("📦 OrderFlow360 - Order Fulfillment Dashboard")
st.caption("Source: Postgres warehouse (schema dw) · refreshed by Airflow reporting_dag")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

tab1, tab2, tab3, tab4 = st.tabs(["Executive Summary", "Courier Performance", "Trends", "Data Quality"])

# ---------- Tab 1 ----------
with tab1:
    st.subheader("Order metrics")
    c = st.columns(5)
    c[0].metric("Total orders", f"{int(orders.total_orders):,}")
    c[1].metric("Delivered", f"{int(orders.delivered_orders):,}")
    c[2].metric("Cancelled", f"{int(orders.cancelled_orders):,}")
    c[3].metric("Returned", f"{int(orders.returned_orders):,}")
    c[4].metric("In transit", f"{int(orders.in_transit_orders):,}")

    st.subheader("Fulfillment metrics")
    c = st.columns(6)
    c[0].metric("Distinct customers", f"{int(cust.distinct_customers):,}")
    c[1].metric("Avg delivery days", f"{ful.avg_delivery_days}")
    c[2].metric("Avg SLA days", f"{ful.avg_sla_days}")
    c[3].metric("On-time %", f"{ful.on_time_delivery_pct}%")
    c[4].metric("Late %", f"{ful.late_delivery_pct}%")
    c[5].metric("Shipment success %", f"{ful.shipment_success_rate_pct}%")

    left, right = st.columns(2)
    status_df = pd.DataFrame({
        "status": ["Delivered", "Cancelled", "Returned", "In Transit"],
        "orders": [orders.delivered_orders, orders.cancelled_orders,
                   orders.returned_orders, orders.in_transit_orders]})
    left.plotly_chart(px.pie(status_df, names="status", values="orders", hole=0.5,
                             title="Order status mix"), use_container_width=True)
    ot = pd.DataFrame({"type": ["On-time", "Late"],
                       "pct": [ful.on_time_delivery_pct, ful.late_delivery_pct]})
    right.plotly_chart(px.pie(ot, names="type", values="pct", hole=0.5,
                              title="Delivered orders: on-time vs late"), use_container_width=True)

    st.subheader("Top 10 customers by orders")
    fig = px.bar(top10.sort_values("total_orders"), x="total_orders", y="customer_id",
                 orientation="h", text="total_orders", hover_data=["customer_name"])
    st.plotly_chart(fig, use_container_width=True)

# ---------- Tab 2 ----------
with tab2:
    b = best_worst.set_index("ranking")
    c1, c2 = st.columns(2)
    if "Best" in b.index:
        c1.success(f"🏆 Best: **{b.loc['Best','courier_name']}** · on-time {b.loc['Best','on_time_pct']}%")
    if "Worst" in b.index:
        c2.error(f"⚠️ Worst: **{b.loc['Worst','courier_name']}** · on-time {b.loc['Worst','on_time_pct']}%")

    l, r = st.columns(2)
    l.plotly_chart(px.bar(courier.sort_values("total_orders", ascending=False),
                          x="courier_name", y="total_orders", title="Orders by courier"),
                   use_container_width=True)
    pct = courier.melt(id_vars="courier_name", value_vars=["on_time_pct", "delay_pct"],
                       var_name="metric", value_name="pct")
    r.plotly_chart(px.bar(pct, x="courier_name", y="pct", color="metric", barmode="group",
                          title="Courier-wise on-time % vs delay %"), use_container_width=True)
    st.dataframe(courier, use_container_width=True, hide_index=True)

# ---------- Tab 3 ----------
with tab3:
    l, r = st.columns(2)
    l.plotly_chart(px.line(m_orders, x="year_month", y="total_orders", markers=True,
                           title="Monthly order trend"), use_container_width=True)
    r.plotly_chart(px.line(m_deliv, x="year_month", y="delivered_orders", markers=True,
                           title="Monthly delivery trend"), use_container_width=True)
    st.plotly_chart(px.bar(status_trend, x="year_month", y="total_orders", color="order_status",
                           title="Status-wise trend"), use_container_width=True)
    picks = st.multiselect("Couriers", sorted(courier_trend.courier_name.unique()),
                           default=sorted(courier_trend.courier_name.unique())[:4])
    ct = courier_trend[courier_trend.courier_name.isin(picks)]
    st.plotly_chart(px.line(ct, x="year_month", y="total_orders", color="courier_name",
                            title="Courier-wise trend"), use_container_width=True)

# ---------- Tab 4 ----------
with tab4:
    audit = q("SELECT dataset, source_rows, valid_rows, rejected_rows, inserted_rows, "
              "updated_rows, unchanged_rows, run_status, run_ts FROM dw.etl_audit ORDER BY run_id DESC")
    st.subheader("ETL audit log")
    st.dataframe(audit, use_container_width=True, hide_index=True)

    rej = q("""SELECT dataset, unnest(string_to_array(reject_reason, ';')) AS reason, count(*) AS rows
               FROM dw.rejected_records GROUP BY 1, 2 ORDER BY rows DESC""")
    st.subheader("Rejected records by reason")
    if rej.empty:
        st.info("No rejected records loaded yet.")
    else:
        st.plotly_chart(px.bar(rej, x="rows", y="reason", color="dataset", orientation="h"),
                        use_container_width=True)
        st.dataframe(rej, use_container_width=True, hide_index=True)