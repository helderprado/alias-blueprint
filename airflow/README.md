# Standalone Airflow service

Airflow is a general workflow orchestrator. Its chart, scheduler, workers and
metadata database do not require OpenMetadata, OpenSearch or MLflow. Installing
or removing the catalog does not install or remove Airflow. The pinned image and
chart stay in `versions.lock.json` and `versions/airflow.values.json`.

## Independent deployment

```sh
cp airflow/.env.example airflow/.env
chmod 600 airflow/.env
# Fill Airflow's own Fernet key, webserver key and external SQLAlchemy database URL.
ALIAS_ENV_FILE="$PWD/airflow/.env" bash airflow/deploy.sh
```

The metadata database must already exist and permit migrations by the supplied
account. Generate the Fernet key with `cryptography.fernet.Fernet.generate_key()`;
keep it and the webserver key stable and backed up. Only AIRFLOW_* settings are
required. The script creates its namespace after validation, then creates missing
runtime Secrets and deploys with atomic Helm rollback. See `scripts/UPGRADES.md`
for the limits of rollback after database migrations.

The default executor is KubernetesExecutor; task Pods run in the Airflow namespace
using the chart's RBAC. No private DAG repository, existing DAG PVC, or catalog
plugin is enabled by default. For application workflows, configure one of:

- Your own DAG source: set `AIRFLOW_DAGS_GIT_REPO` and an exact 40-character commit
  in `AIRFLOW_DAGS_GIT_REF`. Optionally set `AIRFLOW_DAGS_SUBPATH` and the name of
  an existing Git credentials Secret in `AIRFLOW_GIT_CREDENTIALS_SECRET`.
- An existing DAG PVC: set `AIRFLOW_DAGS_PVC` to a claim available in this namespace
  with access modes suitable for scheduler and task Pods.
- A custom versioned image with DAGs baked in: update the image lock together
  with your application image and matching dependency/configuration files.

With neither configured the service starts without your DAGs; it does not reach
out to a private project repository. The legacy `persistent-volume.yaml` is only
an optional environment-specific example and is not applied by deploy.sh. Do not
run `cluster-admin.sh` for a normal installation; the chart creates the executor
RBAC it needs.

Default administrative-user creation is disabled. Configure your authentication
provider or create your first operator interactively using the Airflow CLI in the
webserver Pod; no default login password is shipped. The ClusterIP web interface
can be reached with `kubectl -n airflow port-forward service/airflow-webserver 8080:8080`.

## Optional catalog integration

OpenMetadata's pipeline integration is disabled by default. If it is needed,
configure the catalog to consume a compatible Airflow API and install the matching
OpenMetadata ingestion extensions explicitly in a reviewed image. An ordinary
Airflow server does not automatically provide the OpenMetadata ingestion plugin.
No catalog endpoint or token is required for unrelated DAGs.
