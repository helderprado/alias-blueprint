import subprocess
import uuid
from airflow.models import DagRun, DagModel
from airflow.utils.session import create_session

run_id = 'manual__smoke_' + uuid.uuid4().hex
def loaded():
    with create_session() as session:
        model = session.query(DagModel).filter(DagModel.dag_id == 'alias_smoke').first()
        return model is not None
wait_for(loaded, 'DAG parsing')
subprocess.run(['airflow', 'dags', 'unpause', 'alias_smoke'], check=True, capture_output=True)
subprocess.run(['airflow', 'dags', 'trigger', 'alias_smoke', '--run-id', run_id], check=True, capture_output=True)
def finished():
    with create_session() as session:
        run = session.query(DagRun).filter(DagRun.dag_id == 'alias_smoke', DagRun.run_id == run_id).first()
        if run and run.state == 'failed':
            raise RuntimeError('Scheduled DAG failed')
        return run and run.state == 'success'
wait_for(finished, 'scheduled Airflow -> Spark DAG')
print('PASS: scheduler ran the DAG and awaited Spark completion')
