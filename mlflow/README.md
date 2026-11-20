# MLflow tracking and model registry

MLflow is already deployed by this repository through the community chart, with
chart and image pins in `versions.lock.json` and `versions/mlflow.values.json`.
Both tracking and the model registry use the same MLflow server.

Fill the `MLFLOW_*` section of the root `.env` before running:

```sh
bash /path/to/alias-blueprint/mlflow/deploy.sh
```

The script validates the configuration, creates the namespace and missing runtime
Secret, and runs an atomic Helm upgrade/install. Existing runtime credential
changes are refused. A dedicated external MySQL database and an existing writable
S3-compatible bucket are prerequisites; this deploy does not create them.

The internal API is `http://mlflow.mlflow.svc.cluster.local:5000`. For local use:

```sh
kubectl -n mlflow port-forward service/mlflow 5000:5000
```

Use `http://127.0.0.1:5000` in your MLflow client. Do not expose this default
ClusterIP server publicly without an authentication layer. No public ingress is
installed here. Artifact access uses the database and object-store configuration
supplied in `.env`; bucket permissions and network access must permit the workload.

To catalog models, configure the OpenMetadata MLflow connector as described in
`../openmetadata/README.md`. Deploying these services does not automatically run
a metadata ingestion workflow. See `../scripts/UPGRADES.md` before changing the
server version: metadata database migrations need a matching backup/restore plan.
