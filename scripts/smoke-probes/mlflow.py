from pathlib import Path
import tempfile
import mlflow
from mlflow.tracking import MlflowClient

mlflow.set_tracking_uri('http://127.0.0.1:5000')
client = MlflowClient()
existing = client.get_experiment_by_name('alias_smoke')
experiment = existing.experiment_id if existing else client.create_experiment('alias_smoke')
run = client.create_run(experiment)
run_id = run.info.run_id
client.log_metric(run_id, 'accuracy', 0.75)
with tempfile.TemporaryDirectory() as directory:
    artifact = Path(directory) / 'synthetic.txt'
    artifact.write_text('alias smoke artifact\n')
    client.log_artifact(run_id, str(artifact))
    restored = Path(client.download_artifacts(run_id, 'synthetic.txt', directory + '/download'))
    assert restored.read_text() == artifact.read_text()
assert client.get_run(run_id).data.metrics['accuracy'] == 0.75
client.set_terminated(run_id)
if not any(model.name == SMOKE['model'] for model in client.search_registered_models()):
    client.create_registered_model(SMOKE['model'])
version = client.create_model_version(SMOKE['model'], 'runs:/' + run_id + '/synthetic.txt', run_id)
assert client.get_model_version(SMOKE['model'], version.version).run_id == run_id
assert client.get_registered_model(SMOKE['model']).name == SMOKE['model']
assert any(model.name == SMOKE['model'] for model in client.search_registered_models())
print('PASS: MLflow metric, S3 artifact and registered model')
