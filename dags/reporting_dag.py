from airflow import DAG
from airflow.operators.bash import BashOperator
from common import DEFAULT_ARGS, START, run

with DAG("reporting_dag", default_args=DEFAULT_ARGS, start_date=START,
         schedule=None, catchup=False, tags=["orderflow"]) as dag:

    aggregate_kpis = BashOperator(task_id="aggregate_kpis", bash_command=run("etl/export_kpis.py"))
    reconcile = BashOperator(task_id="reconcile", bash_command=run("etl/reconcile.py"))

    aggregate_kpis >> reconcile