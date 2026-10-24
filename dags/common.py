from datetime import datetime, timedelta

PROJECT = "/opt/airflow/project"
PY = "/home/airflow/etl-venv/bin/python"
START = datetime(2025, 1, 1)


def run(script, *args):
    return f"cd {PROJECT} && {PY} {script} {' '.join(args)}".strip()


def on_failure(context):
    ti = context["task_instance"]
    print(f"[ALERT] {ti.dag_id}.{ti.task_id} failed (try {ti.try_number})")


DEFAULT_ARGS = {
    "owner": "orderflow",
    "retries": 2,
    "retry_delay": timedelta(seconds=30),
    "on_failure_callback": on_failure,
}