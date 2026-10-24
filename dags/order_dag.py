from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from common import DEFAULT_ARGS, START, PROJECT, run

with DAG("order_dag", default_args=DEFAULT_ARGS, start_date=START,
         schedule=None, catchup=False, tags=["orderflow"]) as dag:

    extract = BashOperator(
        task_id="extract",
        bash_command=(f"cd {PROJECT} && ls data/staging/orders_clean_valid.csv "
                      "data/staging/orders_dirty_valid.csv"))
    profile = BashOperator(task_id="profile", bash_command=run("etl/profile_data.py"))
    transform_load = BashOperator(task_id="transform_load",
                                  bash_command=run("etl/load_warehouse.py", "--part", "facts"))
    trigger_reporting = TriggerDagRunOperator(task_id="trigger_reporting_dag",
                                              trigger_dag_id="reporting_dag")

    extract >> profile >> transform_load >> trigger_reporting