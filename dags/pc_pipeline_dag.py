from datetime import datetime, timedelta

from airflow.sdk import dag, task, task_group

DBT = "/Users/krishuang/miniforge3/envs/pc-pipeline/bin/dbt"
DIRS = "--project-dir /Users/krishuang/pc_pipeline --profiles-dir /Users/krishuang/.dbt"


@dag(
    dag_id="pc_pipeline_monthly",
    schedule="@monthly",
    start_date=datetime(2025, 8, 1),
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
)
def pc_pipeline():

    @task_group(group_id="dbt_staging")
    def dbt_staging():
        @task.bash
        def run_staging():
            return f"{DBT} run --select staging {DIRS}"
        run_staging()

    @task_group(group_id="dbt_marts")
    def dbt_marts():
        @task.bash
        def run_marts():
            # same shape as dbt_staging: define a @task.bash, then call it
            return f"{DBT} run --select staging+ --exclude staging {DIRS}"
        run_marts()

    @task_group(group_id="dbt_tests")
    def dbt_tests():
        @task.bash
        def run_tests():
            # test everything, hence no select statement
            return f"{DBT} test {DIRS}"
        run_tests()

        # call all three groups and chain them with >>, in one line. Indentation is key!
    dbt_staging() >> dbt_marts() >> dbt_tests()


pc_pipeline()                  # the line that makes the DA
