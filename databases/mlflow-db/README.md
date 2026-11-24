# MySQL 8.4 backend for MLflow

`deploy.yaml` uses the locked official MySQL **8.4.7** image. MLflow tracking and
model registry share this backend; registry queries need window functions absent
from the old 5.7 example. Airflow, Superset and OpenMetadata use PostgreSQL in the
repository profiles and do not require a MySQL change.

For a new installation, prepare a private copy of `deploy.yaml`, replacing
`VOLUME_PATH_MYSQL84` with a new, empty directory on the node identified by
`HOSTNAME_DNS`. The static PV/PVC have distinct 8.4 names, explicit binding and
Retain reclaim policy. The Deployment uses Recreate to avoid concurrent database
processes on the same data directory.

Create private database credentials and edit both nonempty passwords:

```sh
install -m 600 databases/mlflow-db/.env.example databases/mlflow-db/.env
# Edit databases/mlflow-db/.env locally before continuing.
kubectl apply -f databases/namespace.yaml
kubectl -n databases create secret generic mlflow-db84-secret \
  --from-env-file=databases/mlflow-db/.env
kubectl apply -f /path/to/private-prepared-mysql84.yaml
kubectl -n databases rollout status deployment/mlflow-db --timeout=300s
```

The official image consumes `MYSQL_*` variables from that Secret. The previous
`MLFLOW_DATABASE_*` variables did not initialize the official image. The manifest
does not include an empty Secret that could overwrite existing credentials.
Initialization variables create users/databases only on a fresh data directory;
editing them is not a password-rotation procedure.

Set MLflow's own environment to the same database, user and application password:
`MLFLOW_DB_HOST=mlflow-db-service.databases.svc.cluster.local`,
`MLFLOW_DB_PORT=3306`, `MLFLOW_DB_NAME=mlflow`, `MLFLOW_DB_USER=mlflow` and
`MLFLOW_DB_PASSWORD` matching `MYSQL_PASSWORD`. The application does not use the
root password. `log_bin_trust_function_creators=1` permits MLflow's migration
triggers without granting its database account SUPER privileges. The default
MySQL 8.4 authentication remains enabled.

For an existing 5.7 database, preserve its PV/PVC and take a verified backup before
planning migration. Never attach the old data directory to this 8.4 Deployment.
The supported server upgrade route is **5.7 → 8.0 → 8.4**, with compatibility
checks and backups at each step; see [MySQL upgrade paths](https://dev.mysql.com/doc/refman/8.4/en/upgrade-paths.html).
The new PVC is empty and does not contain existing runs or models. Applying this
manifest to an existing Deployment switches its backend storage; schedule that
cutover only after migrating and verifying the data. No migration or deletion of
existing database data is performed by the smoke runner.

Repeat the real article installer and the affected integration checks in a
disposable Docker/systemd host:

```sh
ALIAS_RUN_K3S_E2E=1 ALIAS_E2E_COMPONENTS=openmetadata \
  python3 -m unittest discover -s scripts/tests -p test_live_k3s.py -v
```

This checks MySQL version, SQL round trip from another Pod, window functions,
application-owned triggers, MLflow runs/metrics/S3 artifacts/model listing, and
OpenMetadata's MLflow API import and search. The runner reads the Deployment from
this manifest, substituting test names, Secret references and a K3s local-path
PVC. It preserves its image, arguments, probes and update strategy. Static
host-path provisioning and migration of existing 5.7 data are outside this test.

Verification run `20261123T204133Z-bd22d5` passed all 11 report entries, including
the article installer, MySQL/MLflow/OpenMetadata integration and cleanup. The
native sequence took 684.9 seconds; the enclosing automated test took
695.498 seconds (about 11 min 35 s). The test host and anonymous volumes were
removed. The local suite passed 61 tests with two optional checks skipped;
the live test above was executed separately.

Local evidence:

```text
.local-smoke/hosts/20261123T204133Z-bd22d5/host-report.json
.local-smoke/hosts/20261123T204133Z-bd22d5/artifacts/20261123T204141Z-54f3e6/report.json
```
