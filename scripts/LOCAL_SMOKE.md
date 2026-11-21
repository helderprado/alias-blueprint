# Local installation and functional smoke checks

From the repository root:

```sh
bash install.sh --plan
bash install.sh --check
bash install.sh --run
```

`--run` creates a disposable, single-node K3s cluster in a privileged Docker
container. It uses the K3s/Helm versions, chart checksums, image digests,
component values, runtime Secret builders and image recipes in this repository.
This exercises a local installation; it does not run the host-level
`install-k3s.sh`, install Rancher on your existing cluster, or read your kubeconfig.
No existing component `.env`, credentials or volumes are reused. A source snapshot
contains only versioned repository files; edits to versioned files are included.

Linux/WSL2 amd64, a working local Docker daemon, Python 3 with venv support,
Git, OpenSSL and Java `keytool` must be available. For WSL2, enable Docker Desktop
integration for the distribution first. Registry charts, images, Python packages,
Go modules and Maven artifacts require outbound network access. The runner checks
Docker before downloading or building anything. Helm and Python dependencies are
prepared under ignored `.local-smoke/` when the locked versions are unavailable.
`ALIAS_HELM=/absolute/path/to/helm` can select the locked Helm client.

The complete sequence targets a machine with 6 CPUs and 15 GiB RAM, with about
12 GiB available, and sufficient disk space for images, Go build caches and PVCs.
This is a target footprint, not a measured successful full-stack deployment.
The runner refuses to start below 8 GiB available. Services are unloaded after
their final consumer to release memory; the local Trino profile uses smaller
heaps and resource requests. Persistent data stays in the disposable node until
that node is removed. Initial source builds of MinIO and Spark can take much
longer than subsequent runs.

## Coverage

| Stage | Functional assertion |
|---|---|
| Bootstrap | Install isolated K3s; wait for node and DNS readiness |
| Storage | One Pod writes a PVC; a different Pod reads the same bytes |
| Databases | PostgreSQL and MySQL insert/select/drop temporary tables; create separate application users/databases |
| Registry | Authenticated image push, verified manifest digest, then Kubernetes pulls/runs that image |
| MinIO | Build the committed source recipe, provision bucket-scoped accounts; upload/download/delete an object |
| MLflow | Persist a run and metric in MySQL, retrieve an S3 artifact, create a model version |
| Spark Operator / Spark | Build the committed S3 image; distributed computation and Parquet write/read/delete on MinIO |
| Airflow | The scheduler executes a DAG that submits and awaits a distributed Spark application |
| JupyterHub | Authenticated Hub API creates a user and spawns a ready notebook; code inside that Pod submits and awaits Spark |
| OpenSearch | Trusted TLS and authentication; index/search/delete a synthetic document |
| OpenMetadata | Import an MLflow model using service APIs, retrieve the catalog entity and find it through OpenSearch |
| Pinot | Create schema/table, ingest three JSON rows and check count=3/sum=60 through the broker |
| Trino | Authenticated TLS SQL checks TPC-H count=25 and Pinot count=3/sum=60 |
| Superset | Use its SQLAlchemy source to query Trino/Pinot; save a dataset, chart and dashboard; write/read/delete a Redis cache entry; check HTTP health |
| pgAdmin | Submit the login form; use the configured server definition to connect to PostgreSQL from the pgAdmin Pod |
| Homepage | Check HTML and the local service links returned by its configuration API |
| cert-manager | Issue a self-signed certificate and check the Ready condition and TLS Secret |
| Rancher | Private HTTP readiness, bootstrap authentication and local cluster API |
| GlusterFS | Report BLOCKED: the replicated profile needs three separately prepared storage hosts |

OpenMetadata uses basic/JWT authentication exclusively in the local override.
External OIDC, browser login, the official MLflow ingestion connector and its
Airflow ingestion plugin are outside this test. The metadata import is a direct
API workflow. JupyterHub uses the repository's dummy authenticator; notebook code
is executed in the spawned Pod, rather than through the browser/kernel protocol.
Superset checks the query and stored dashboard objects, not browser rendering.
pgAdmin's database check uses its Python environment and server definition, not
the query-tool UI. Rancher uses its namespace's private HTTP service; public
ingress, routing and HTTPS termination are outside this local check. Trino and
OpenSearch retain certificate verification. Local PVC checks do not validate
GlusterFS replication, NFS-Ganesha, failover, throughput or production security.

Only the Kubernetes API and authenticated registry publish ports on host
loopback. Other component endpoints remain inside the disposable cluster.
OpenSearch may temporarily raise the Docker kernel's `vm.max_map_count`; the
previous value is restored on normal exit or Ctrl+C, including with `--keep`.
An uncatchable termination such as SIGKILL can prevent that restoration.

## Select components and inspect failures

Dependencies are included automatically, in order:

```sh
bash install.sh --run --components spark
bash install.sh --run --components superset
bash install.sh --run --components airflow,jupyterhub,openmetadata,superset,pgadmin,homepage,rancher
```

The last command selects all locally testable components, excluding the known
multi-host GlusterFS limitation. `--components all` is the default and explicitly
includes that limitation as a BLOCKED result, so it cannot return complete success
on a single-node machine.

Deployment/probe deadlines default to 900 seconds; each custom image build/push
can take up to 3600 seconds. Override with `--timeout` and `--build-timeout`.

Each invocation writes its own directory:

```text
.local-smoke/runs/RUN_ID/
  report.json          statuses, purposes, elapsed times and validation limits
  report.txt           short readable result
  logs/                redacted command output and failure diagnostics
  project/             source snapshot and generated component credentials
  test.env             generated test-only inputs
  kubeconfig           access only to this disposable cluster
```

Reports, inputs and logs are private files. Generated credentials are removed from
command logs; kubeconfig/Secret reads suppress their output. The directory still
contains credentials and keys needed by the test installation, and is ignored by
Git. Do not publish the entire run directory. Charts, downloaded images and build
layers remain cached for reuse.

Results distinguish `PASS`, `FAIL`, `BLOCKED` and `NOT_RUN`. A dependency failure
blocks its consumers; independent stages continue. Preflight failure records
NOT_RUN for every component and exits nonzero without provisioning a cluster.
The exit code is zero only when every selected functional stage and cleanup
succeeds. `--check` only checks prerequisites and deliberately records functional
checks as NOT_RUN; it is not a functional success report.

The cluster and its anonymous data volumes are removed after diagnostics, even
when installation or a probe fails. Retain them for inspection with:

```sh
bash install.sh --run --components spark --keep
docker exec -it alias-smoke-RUN_ID_LOWERCASE k3s kubectl get pods -A
bash install.sh --cleanup RUN_ID
```

The report records the exact container name. Finished services are still unloaded
with `--keep`; retained PVCs and logs support inspection without requiring all
services to stay in RAM. Explicit cleanup checks the container's ownership label
before deleting it. It does not prune unrelated Docker images or containers.

## Validate the runner without services

```sh
python3 -m unittest discover -s scripts/tests -p 'test_local_smoke*.py' -v
```

Optional offline rendering checks the actual local overrides against checksum-
verified official chart archives (the directory uses `NAME-VERSION.tgz` filenames):

```sh
ALIAS_HELM=/path/to/helm \
ALIAS_SMOKE_CHARTS_DIR=/path/to/verified/charts \
python3 -m unittest discover -s scripts/tests -p test_local_smoke_charts.py -v
```

These checks validate orchestration/failure behavior and rendered manifests;
they never establish a running service or successful cross-service operation.

Implementation references: [K3s in Docker](https://docs.k3s.io/advanced),
[Pinot's small-file upload API](https://docs.pinot.apache.org/build-with-pinot/ingestion/batch-ingestion/batch-ingestion),
[JupyterHub API](https://jupyterhub.readthedocs.io/en/4.x/reference/rest-api.html).
