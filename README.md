# OrderFlow360 – Order Fulfillment Analytics Platform

End-to-end local data engineering project for an e-commerce order fulfillment use case.
Source CSVs are validated, loaded into a Postgres star-schema warehouse, orchestrated with
**Apache Airflow**, and visualised in a **Streamlit** KPI dashboard. Everything runs locally with **Docker**.

## Architecture

```
Source CSVs ─► Validate (pandas) ─► Staging / Rejected ─► Load dims + facts (SQLAlchemy)
                                                              │
                                      Airflow: order_dag ─► reporting_dag
                                                              │
                                   Postgres warehouse (schema dw) ─► KPI views ─► Streamlit dashboard
```

- **Layers:** raw (`data/source`) → staging (`data/staging`, `data/rejected`) → curated warehouse (`dw` schema)
- **Dimensions:** `dim_customer` (SCD Type 2), `dim_courier`, `dim_product`, `dim_date`
- **Fact:** `fact_order_fulfillment` (grain: one row per ORDER_ID)
- **Audit / error handling:** `etl_audit`, `rejected_records`, reconciliation reports

## Folder structure

```
orderflow360/
├── dags/                     # Airflow DAGs
│   ├── common.py             # shared config, retries, failure callback
│   ├── order_dag.py          # extract → profile → transform_load → trigger reporting_dag
│   └── reporting_dag.py      # aggregate KPIs → reconcile
├── etl/                      # ETL scripts
│   ├── validate.py           # data-quality rules, writes staging + rejected files
│   ├── profile_data.py       # profiling reports
│   ├── load_warehouse.py     # loads dimensions and facts (--part dims|facts|all)
│   ├── export_kpis.py        # exports KPI views to CSV
│   └── reconcile.py          # reconciliation checks
├── sql/
│   ├── 01_ddl.sql            # warehouse DDL (star schema, audit tables)
│   └── 02_kpi_views.sql      # KPI views (dw.kpi_*)
├── dashboard/                # Streamlit dashboard
│   ├── app.py
│   └── requirements.txt
├── data/
│   ├── source/               # input CSVs
│   ├── staging/              # valid records (generated)
│   ├── rejected/             # rejected records (generated)
│   └── reference/            # expected issues, KPI assumptions
├── reports/                  # profiling, reconciliation, KPI CSV outputs (generated)
├── k8s/                      # Kubernetes manifests
├── tests/                    # unit tests
├── Dockerfile                # application image
├── Dockerfile.airflow        # Airflow image (with ETL virtualenv)
├── Dockerfile.dashboard      # dashboard image
├── Jenkinsfile               # CI/CD pipeline
├── docker-compose.yml        # Postgres, Airflow, dashboard
├── requirements.txt
└── requirements-etl.txt
```

## Prerequisites

- Docker Desktop (running)
- Python 3.11 (only needed to run the dashboard or scripts outside Docker)
- VS Code (optional)

## Services and ports

| Service            | URL / Port                | Credentials                          |
|--------------------|---------------------------|--------------------------------------|
| Airflow UI         | http://localhost:8080     | admin / admin                        |
| Warehouse Postgres | localhost:5433            | orderflow / orderflow123, db `orderflow_dw` |
| Streamlit          | http://localhost:8501     | –                                    |

## Setup

Run all commands from the project root (the folder containing `docker-compose.yml`).

```bat
docker compose up -d --build
docker compose ps
```

Postgres creates the warehouse tables and KPI views from `sql/` on first start.

## Run the ETL pipeline

**1. Validate source files** (creates `data/staging` and `data/rejected`):
```bat
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/project && /home/airflow/etl-venv/bin/python etl/validate.py"
```

**2. Load dimension tables** (date, courier, customer):
```bat
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/project && /home/airflow/etl-venv/bin/python etl/load_warehouse.py --part dims"
```

**3. Trigger the Airflow DAGs.** `order_dag` loads facts, then triggers `reporting_dag`, which exports KPIs and runs reconciliation:
```bat
docker compose exec airflow-scheduler airflow dags trigger order_dag
docker compose exec airflow-scheduler airflow dags list-runs -d order_dag
docker compose exec airflow-scheduler airflow dags list-runs -d reporting_dag
```
Both runs should end in state `success`. You can also watch them in the Airflow UI.

**4. Verify the warehouse:**
```bat
docker compose exec postgres psql -U orderflow -d orderflow_dw -c "SELECT * FROM dw.kpi_order_summary;"
```

## Run the Streamlit dashboard

**Option A – Docker:**
```bat
docker compose up -d --build dashboard
docker compose logs --tail 30 dashboard
```

**Option B – local virtual environment** (Postgres container must be running):
```bat
python -m venv venv
venv\Scripts\activate
pip install -r dashboard\requirements.txt
streamlit run dashboard\app.py
```

Open http://localhost:8501. Tabs: Executive Summary, Courier Performance, Trends, Data Quality.
Use the sidebar button to refresh after re-running the pipeline.

## Data-quality rules

Records are rejected (and logged with a reason) for: null order/customer/product/courier ID,
invalid or future order dates, non-positive or non-numeric quantity, delivery before shipped/order,
shipped before order, delivered without delivery date, unknown customer or courier,
invalid status, and older duplicate ORDER_ID versions.
See `reports/reject_summary.csv` and `reports/reconciliation_report.csv`.

## KPIs

| Group       | KPIs |
|-------------|------|
| Order       | Total, Delivered, Cancelled, Returned, In-Transit orders |
| Customer    | Distinct customers, Top 10 customers by orders |
| Fulfillment | Avg delivery days, Avg SLA days, On-time %, Late %, Shipment success rate |
| Courier     | Orders by courier, on-time %, delay %, best and worst courier |
| Trend       | Monthly order and delivery trend, status-wise trend, courier-wise trend |

KPI assumptions are documented in `data/reference/kpi_definition_assumptions.csv`.

## Useful commands

```bat
docker compose logs -f airflow-scheduler    :: follow scheduler logs
docker compose restart dashboard            :: restart the dashboard
docker compose down                         :: stop everything (data kept)
docker compose down -v                      :: stop and wipe all databases, then re-run the ETL steps
```

## Troubleshooting

- **`no configuration file provided`:** you are not in the folder containing `docker-compose.yml`.
- **`TLS handshake timeout` during build:** Docker Hub is unreachable; retry, change network, or run the dashboard with Option B.
- **Dashboard says "Could not read KPI views" or "Warehouse is empty":** the ETL has not finished; check that both DAG runs are `success`.
- **`additional properties ... not allowed` in compose:** a YAML indentation problem; services must be indented exactly 2 spaces. Check with `docker compose config --quiet`.
- **Slow installs or file locks:** the project is inside OneDrive; move it to a plain path such as `C:\projects\orderflow360`.