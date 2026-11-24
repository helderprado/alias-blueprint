# ALIAS Blueprint

Deployment scripts, manifests and configuration for the ALIAS architecture
for intelligent healthcare auditing.

- **License:** Apache 2.0 (see `LICENSE`)
- **Component versions:** see `VERSIONS.md`

## Terminology

The documentation uses the following conventions:

| Term | Meaning and spelling |
|---|---|
| Spark Operator | The named Kubernetes component that manages Spark jobs. Use the full name in prose. |
| operator | A generic Kubernetes controller that reconciles application resources. For the person managing a deployment, use administrator. An Airflow Operator is a task implementation, not a Kubernetes operator or a user account. |
| DAG / DAGs | Directed acyclic graph (plural DAGs). In Airflow, the definition of tasks and their dependencies for a workflow. Use uppercase DAG and the plural DAGs. |
| pipeline | An end-to-end data-processing flow. A pipeline can span Airflow DAGs, Spark jobs and other services; it is not a synonym for a DAG. OpenMetadata ingestion workflows are identified explicitly. |
| big data | Write as two lowercase words in prose. |
| Tool names | Apache Spark, Spark Operator, Apache Airflow, JupyterHub, MLflow, OpenMetadata, OpenSearch, Trino, Apache Pinot, Apache Superset, MinIO, GlusterFS, NFS-Ganesha, PostgreSQL, MySQL, pgAdmin, Homepage, Rancher, K3s, Helm and Kubernetes. Spark, Airflow, Pinot and Superset are the short forms after the full name is introduced. |

Paths, commands, API fields, chart/release names, image references and environment
variables retain their exact spelling and case, even when they differ from prose.

## 1. What this repository contains

The inventory below maps each of the architecture's nine layers to the
committed implementation.
Dependencies describe the current deployment configuration; connections marked
optional require explicit configuration. See `VERSIONS.md` for exact releases
and validation limits.

| # | Layer / component | Repository paths | Provisioning | Dependencies |
|---|---|---|---|---|
| 1 | Infrastructure and security: K3s, Rancher, RBAC | `install-k3s.sh`, `k3s-config.yaml`, `kube-config.sh`, `install-rancher.sh`; component `*/service-account*.yaml` files | Shell installs K3s; Helm installs cert-manager and optional Rancher; `kubectl apply` for RBAC manifests | Host OS and network; cluster access; Helm for Rancher, which uses cert-manager. Component service accounts and role bindings must be applied separately where provided. |
| 2 | Storage: GlusterFS, persistent volumes and S3-compatible object storage | `glusterfs/`, optional `minio/`; component `persistent-volume.yaml` files, `databases/*/deploy.yaml` and `*/values.yaml` | Bash installs pinned GlusterFS/NFS-Ganesha host packages and creates the volume/export; `glusterfs/deploy.sh` applies static NFS PVs/PVCs; Helm creates other chart-managed PVCs | Existing hosts and mounted brick filesystems; three storage nodes for the replicated profile, a stable NFS gateway and NFS client packages on K3s nodes. Local PV examples remain optional alternatives. S3 endpoints/buckets may be external or provided by the independent MinIO profile. |
| 3 | Processing and AI: Apache Spark, Spark Operator, ETL images | `spark/`, `spark-operator/`, `docker-images/pyspark-aws-psql/`, `docker-images/etl-base-image/`; [Spark procedure](spark/README.md) | Helm installs the Spark Operator and its CRDs; `spark/setup.sh` prepares namespace-scoped driver RBAC, optional runtime Secrets and aggregate quotas; `spark/submit.sh` creates the bounded smoke job | K3s, Helm, webhook connectivity and locked workload images. MinIO/external S3, JDBC and a read-only shared PVC are optional. The smoke check is supplied; domain ETL pipelines and trained models must be supplied separately. |
| 4 | Analysis and development: JupyterHub | `jupyterhub/deploy.sh`, `jupyterhub/values.yaml`, `jupyterhub/persistent-volume.yaml`, `jupyterhub/service-account*.yaml`, `jupyterhub/images/hub/` | Helm via `deploy.sh`; `kubectl apply` for namespace, static storage and service account/RBAC; optional custom image build | K3s, Helm, `JUPYTERHUB_*` runtime Secret; existing `nfs-share-pvc`, service account `spark`, and referenced pull secret `regcred`. Spark namespace/RBAC is needed for notebook-submitted Spark workloads. |
| 5 | Workflow orchestration: Apache Airflow | `airflow/deploy.sh`, `airflow/values.yaml`, `airflow/persistent-volume.yaml`, `airflow/image/` | Helm via `deploy.sh`, which prepares namespace and runtime Secrets; optional static PVC / custom image build | K3s, Helm, external metadata database, Fernet and webserver keys. Optional DAG Git source requires an exact commit; optional DAG PVC must exist. Spark integration requires separately supplied DAGs and Spark resources. |
| 6 | Model lifecycle: MLflow tracking and registry | `mlflow/deploy.sh`, `mlflow/values.yaml`, `mlflow/README.md` | Helm via `deploy.sh`, which prepares namespace and runtime Secret | K3s, Helm, existing MySQL 8.4 database/user and writable S3-compatible bucket/endpoint; `MLFLOW_*` configuration. Neither database nor bucket is created by this script. |
| 7 | Catalog and governance: OpenMetadata | `openmetadata/gen-keys.sh`, `openmetadata/deploy.sh`, `openmetadata/values.yaml`, `openmetadata/README.md` | Shell generates local JWT keys; Helm via `deploy.sh` prepares namespace and Secrets, verifies the chart and pins its test image | K3s, Helm, dedicated PostgreSQL database, OpenSearch endpoint/account, OIDC provider and JWT/Fernet keys. `opensearch/` can supply the search endpoint. MLflow ingestion is optional and separately configured; automatic deployment of OpenMetadata ingestion DAGs through Airflow is disabled. |
| 8 | Query: Trino and Apache Pinot | `trino/gen-security.sh`, `trino/deploy.sh`, `trino/values.yaml`, `trino/catalogs.example.json`; `pinot/deploy.sh`, `pinot/values.yaml` | Shell generates Trino authentication/TLS material; separate Helm deployments prepare namespaces, Secrets/policies and workloads | K3s, Helm and a CNI enforcing NetworkPolicy. Trino needs `TRINO_*` credentials and starts with synthetic catalogs; external sources are optional. Pinot needs persistent storage and ZooKeeper (bundled by default). The Trino–Pinot connection is optional. |
| 9 | Visualization: Apache Superset | `superset/deploy.sh`, `superset/values.yaml`, `superset/requirements.lock` | Helm via `deploy.sh`; runtime Secret and hashed Python extension installation during bootstrap; chart-managed Redis | K3s, Helm, existing namespace, external PostgreSQL database/user, `SUPERSET_*` keys and Redis password; persistent storage for Redis. Query-source connections such as Trino must be configured separately. |

Upstream Helm chart deployments use `scripts/versions.sh`, `versions.lock.json`,
`versions/*.values.json` and `scripts/locked-images.py`. Runtime configuration
and Secret creation use `scripts/env.sh`, `scripts/runtime.sh` and
`scripts/runtime-secrets.py` where invoked; install `scripts/requirements.txt`
in that Python environment. See `scripts/README.md` for per-component behavior.
The optional [MinIO profile](minio/README.md) uses a local Helm chart and a
source-built image supplied by its actual registry digest; its source/toolchain
pins are recorded separately in `versions.lock.json`.

The storage manifests contain `local.path` and node-affinity placeholders that
must be adapted before use. Names such as `nfs-share-pv` do not provision an NFS
server or a shared filesystem: those manifests declare local volumes. For
shared storage, use the optional [GlusterFS profile](glusterfs/README.md), which
provides host provisioning scripts and NFSv4.1 PVs for JupyterHub, Airflow,
Spark jobs and optionally the registry. The current Spark job namespace uses
the opt-in `spark` storage profile; `spark-operator` remains a legacy profile.
Choose one provider for each claim;
existing data requires a separate migration. Chart deployments do not apply the
separate static PV/PVC files.

Supporting components are outside the nine-layer numbering:

| Component | Repository paths | Provisioning | Dependencies |
|---|---|---|---|
| Private registry | `registry/` | Shell generates htpasswd and pull Secrets; Helm deploys the registry; separate PVC manifest | Existing namespace and `docker-registry-pv-claim`; storage and registry credentials. Optional when only public images are used, subject to component pull-secret settings. |
| Optional S3 service: MinIO | `minio/configure.py`, `minio/build-image.sh`, `minio/deploy.sh`, `minio/connection.sh`, `minio/chart/` | Interactive local configuration; source-built server/client image; independent Helm release and scoped bucket accounts | K3s, Helm, registry access, an explicit StorageClass or dedicated PVC; optional TLS/pull Secrets. Separate AGPLv3 component; archived Community upstream. See [MinIO](minio/README.md). |
| Database examples: PostgreSQL and MySQL | `databases/namespace.yaml`, `databases/prod-db/deploy.yaml`, `databases/superset-db/deploy.yaml`, `databases/mlflow-db/deploy.yaml` | Manual configuration and `kubectl apply` | Node paths, namespace and freshly supplied database credentials. Application deploy scripts do not apply these examples or create their external databases. See [MySQL 8.4 setup and migration](databases/mlflow-db/README.md). |
| Database administration: pgAdmin | `pgadmin/` | `deploy.sh` applies Secret, Deployment and Service manifests | Existing namespace, supplied login Secret and separately configured database connections. |
| Landing page: Homepage | `homepage/` | Helm via `deploy.sh` | Existing namespace; service URLs configured in `values.yaml`. |
| Search backend: OpenSearch | `opensearch/` | Shell generates TLS/security material; Helm via `deploy.sh` | Persistent storage and `OPENSEARCH_*` credentials. Independently deployable; consumers configure their own endpoint/account. |
| Image build recipes | `docker-images/`, `airflow/image/`, `jupyterhub/images/hub/` | Manual container builds from Dockerfiles and dependency locks | Container build tooling and artifact access; a registry accessible to workloads for custom images. Builds are not invoked by component deployment scripts. |

## 2. Requirements

- Base operating system: Ubuntu 22.04 LTS, amd64, as recorded in
  `versions.lock.json`. Host creation and OS installation are external.
- CPU, memory and storage capacity sized for the selected components' resource
  requests and volume requirements. The optional GlusterFS replicated profile
  uses groups of three storage nodes and a dedicated mounted filesystem per node.
- CPU-only. No GPU or TPU is required for the baseline ETL, training,
  or inference workloads.
- K3s-bundled `kubectl` for `v1.34.13+k3s1` and Helm `v3.17.3`;
  see `VERSIONS.md` for the complete baseline.
- Outbound network access for image and chart retrieval.

## 3. Required configuration

No credential is versioned in this repository. Copy [.env.example](.env.example)
to `.env`, restrict it with `chmod 600 .env`, and fill the sections for the
components being deployed. Unused component sections may remain empty. Deployment
scripts validate required inputs before contacting Kubernetes. Variables below
configure the deployment scripts and the runtime Secrets referenced by the
manifests; defaults and optional integrations are identified explicitly.

| Variable | Purpose |
|----------|---------|
| `ALIAS_ENV_FILE` | Optional trusted Bash configuration file instead of the root `.env`; file assignments override exported variables. See [configuration loading](scripts/README.md). |
| `K3S_VERSION` | Exact K3s release used by `install-k3s.sh`; defaults to the committed pin. |
| `K3S_CONFIG` | Optional path to the K3s configuration; defaults to the repository's `k3s-config.yaml`. |
| `REGISTRY_HOST` | Host and port of the private registry. |
| `REGISTRY_USER`, `REGISTRY_PASSWORD` | Registry credentials supplied at runtime; use a dedicated non-administrative account. |
| `REGISTRY_SERVICE_ACCOUNT` | Pull-secret ServiceAccount; defaults to `registry-puller`. |
| `JUPYTERHUB_CRYPT_KEY`, `JUPYTERHUB_AUTH_PASSWORD` | Required Hub encryption key and dummy-authenticator password. Generate the crypt key with `openssl rand -hex 32`. |
| `MLFLOW_DB_HOST`, `MLFLOW_DB_PORT`, `MLFLOW_DB_NAME`, `MLFLOW_DB_USER`, `MLFLOW_DB_PASSWORD` | Existing MySQL database and credentials for MLflow; port defaults to `3306`. |
| `MLFLOW_S3_BUCKET`, `MLFLOW_S3_ENDPOINT_URL`, `MLFLOW_S3_ACCESS_KEY_ID`, `MLFLOW_S3_SECRET_ACCESS_KEY` | Existing writable artifact bucket, HTTP(S) endpoint and scoped S3 credentials. See [MLflow](mlflow/README.md). |
| `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` | Manual MySQL example: values for `mlflow-db84-secret`, configured separately in [databases/mlflow-db/.env.example](databases/mlflow-db/.env.example). Match the application account to `MLFLOW_DB_*`; see [database setup](databases/mlflow-db/README.md). |
| `SUPERSET_SECRET_KEY` | Required Superset application secret; generate with `openssl rand -hex 32`. |
| `SUPERSET_DB_HOST`, `SUPERSET_DB_NAME`, `SUPERSET_DB_USER`, `SUPERSET_DB_PASSWORD` | Existing PostgreSQL metadata database and credentials for Superset, using port `5432`. |
| `SUPERSET_REDIS_PASSWORD` | Required password for chart-managed Redis. |
| `AIRFLOW_CHART_VERSION`, `AIRFLOW_VALUES` | Exact chart release (defaults to the version lock) and optional alternate values file. |
| `AIRFLOW_FERNET_KEY`, `AIRFLOW_WEBSERVER_SECRET_KEY` | Required Fernet encryption key and webserver signing secret. Generate Fernet with `cryptography.fernet.Fernet.generate_key().decode()` in Python. |
| `AIRFLOW_DATABASE_URL` | Complete SQLAlchemy URL for an existing metadata database; URL-encode special characters in credentials. |
| `AIRFLOW_DAGS_GIT_REPO`, `AIRFLOW_DAGS_GIT_REF`, `AIRFLOW_DAGS_SUBPATH`, `AIRFLOW_GIT_CREDENTIALS_SECRET` | Optional Git DAG source, exact 40-character commit, subdirectory and existing credential Secret. |
| `AIRFLOW_DAGS_PVC` | Optional existing DAG claim in `airflow`; see [Airflow](airflow/README.md) for DAG delivery choices. |
| `OPENSEARCH_ADMIN_USER`, `OPENSEARCH_ADMIN_PASSWORD`, `OPENSEARCH_TRUSTSTORE_PASSWORD` | OpenSearch administrator identity and security-material passwords; run `opensearch/gen-security.sh` before deployment. |
| `OPENSEARCH_APP_USER`, `OPENSEARCH_APP_PASSWORD`, `OPENSEARCH_APP_INDEX_PATTERNS` | Optional application account: set both credentials or leave both empty; index patterns default to `app-*`. See [OpenSearch](opensearch/README.md). |
| `OPENMETADATA_JWT_PRIVATE_KEY_FILE`, `OPENMETADATA_JWT_PUBLIC_KEY_FILE` | DER JWT key files; defaults point to `openmetadata/runtime-creds/`. Generate with `bash openmetadata/gen-keys.sh`. |
| `OPENMETADATA_FERNET_KEY`, `OPENMETADATA_PUBLIC_URL` | Required separate Fernet key and public application URL. |
| `OPENMETADATA_ADMIN_PRINCIPAL`, `OPENMETADATA_PRINCIPAL_DOMAIN` | Initial administrator's identity-provider principal and domain. |
| `OPENMETADATA_OIDC_AUTHORITY`, `OPENMETADATA_OIDC_DISCOVERY_URL`, `OPENMETADATA_OIDC_JWKS_URL`, `OPENMETADATA_OIDC_CLIENT_ID`, `OPENMETADATA_OIDC_CLIENT_SECRET` | Required OIDC provider endpoints and client credentials. |
| `OPENMETADATA_DB_HOST`, `OPENMETADATA_DB_PORT`, `OPENMETADATA_DB_NAME`, `OPENMETADATA_DB_USER`, `OPENMETADATA_DB_PASSWORD`, `OPENMETADATA_DB_PARAMS` | Existing PostgreSQL database and credentials; port defaults to `5432` and connection parameters to `sslmode=require`. |
| `OPENMETADATA_SEARCH_HOST`, `OPENMETADATA_SEARCH_PORT`, `OPENMETADATA_SEARCH_SCHEME`, `OPENMETADATA_SEARCH_USER`, `OPENMETADATA_SEARCH_PASSWORD` | Independently provisioned search endpoint/account; defaults are HTTPS and port `9200`. |
| `OPENMETADATA_SEARCH_TRUSTSTORE_FILE`, `OPENMETADATA_SEARCH_TRUSTSTORE_PASSWORD` | Optional truststore for a private search CA; leave empty for a publicly trusted CA. See [OpenMetadata](openmetadata/README.md). |
| `TRINO_USER`, `TRINO_PASSWORD`, `TRINO_SHARED_SECRET` | Required SQL account and stable cluster shared secret; generate security material with `bash trino/gen-security.sh`. |
| `TRINO_WORKERS`, `TRINO_ALLOWED_NAMESPACES`, `TRINO_CATALOGS_FILE` | Worker count (default `1`), optional permitted client namespaces and optional JSON catalog configuration. See [Trino](trino/README.md). |
| `PINOT_CLUSTER_NAME`, `PINOT_ZOOKEEPER_URL`, `PINOT_STORAGE_CLASS`, `PINOT_ALLOWED_NAMESPACES` | Pinot cluster name (default `pinot`), optional external ZooKeeper, storage class and trusted client namespaces. Empty ZooKeeper/storage settings select bundled ZooKeeper/default StorageClass. See [Pinot](pinot/README.md). |
| `GLUSTERFS_NODES`, `GLUSTERFS_NFS_SERVER`, `GLUSTERFS_CLIENT_CIDRS` | Optional shared-storage hosts, stable NFS gateway and trusted K3s node networks; required when provisioning this storage profile. |
| `GLUSTERFS_VOLUME`, `GLUSTERFS_REPLICA_COUNT`, `GLUSTERFS_BRICK_MOUNT`, `GLUSTERFS_PROFILES` | Volume name, replication, pre-mounted brick filesystem and consumer profiles. Select `spark` for current Spark jobs; `spark-operator` is the legacy profile. |
| `GLUSTERFS_NOTEBOOK_UID`, `GLUSTERFS_NOTEBOOK_GID`, `GLUSTERFS_DAGS_UID`, `GLUSTERFS_DAGS_GID`, `GLUSTERFS_REGISTRY_UID`, `GLUSTERFS_REGISTRY_GID` | Initial numeric directory owners; defaults and complete profile are in [glusterfs/.env.example](glusterfs/.env.example). |
| `SPARK_IMAGE`, `SPARK_IMAGE_PULL_SECRET`, `SPARK_APPLICATION_NAME` | Optional workload image digest/pull Secret and application name. The default smoke image supports compute only; S3/JDBC integrations require a custom image digest. |
| `SPARK_DRIVER_CORES`, `SPARK_DRIVER_CPU_REQUEST`, `SPARK_DRIVER_CPU_LIMIT`, `SPARK_DRIVER_MEMORY`, `SPARK_DRIVER_MEMORY_OVERHEAD` | Driver CPU and memory budget; defaults are in [.env.example](.env.example). |
| `SPARK_EXECUTORS`, `SPARK_EXECUTOR_CORES`, `SPARK_EXECUTOR_CPU_REQUEST`, `SPARK_EXECUTOR_CPU_LIMIT`, `SPARK_EXECUTOR_MEMORY`, `SPARK_EXECUTOR_MEMORY_OVERHEAD` | Executor count and per-executor CPU/memory budget. |
| `SPARK_QUOTA_CPU`, `SPARK_QUOTA_MEMORY`, `SPARK_QUOTA_PODS` | Aggregate limits for all jobs in namespace `spark`; defaults are `4`, `8Gi` and `12`. |
| `SPARK_DAGS_PVC` | Optional existing Bound claim in `spark`, mounted read-only at `/opt/spark/shared`. |
| `SPARK_S3_ENABLED`, `SPARK_S3_ENDPOINT_URL`, `SPARK_S3_BUCKET`, `SPARK_S3_ACCESS_KEY_ID`, `SPARK_S3_SECRET_ACCESS_KEY` | Optional S3 integration, disabled by default; endpoint, bucket and credentials are required when enabled. Generic S3/AWS exports from `minio/connection.sh` are also supported. |
| `SPARK_DB_ENABLED`, `SPARK_DB_URL`, `SPARK_DB_USER`, `SPARK_DB_PASSWORD` | Optional JDBC integration, disabled by default; URL and credentials are required when enabled. See [Spark](spark/README.md). |
| `MINIO_IMAGE`, `MINIO_IMAGE_PULL_SECRET`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Independent optional S3 profile: built image digest, optional pull Secret and required server credentials. Configure in `minio/.env`, selected with `ALIAS_ENV_FILE`. |
| `MINIO_STORAGE_CLASS`, `MINIO_EXISTING_CLAIM`, `MINIO_STORAGE_SIZE` | Choose exactly one storage source: StorageClass or existing Bound claim; requested size defaults to `50Gi`. |
| `MINIO_CPU_REQUEST`, `MINIO_CPU_LIMIT`, `MINIO_MEMORY_REQUEST`, `MINIO_MEMORY_LIMIT` | MinIO server resource requests and limits. |
| `MINIO_TLS_SECRET`, `MINIO_ALLOWED_NAMESPACES`, `MINIO_CLIENTS` | Optional existing TLS Secret, trusted client namespaces and bucket-account profiles. |
| `MINIO_MLFLOW_BUCKETS`, `MINIO_MLFLOW_ACCESS_KEY`, `MINIO_MLFLOW_SECRET_KEY` | MLflow bucket scope and client credentials for the example MinIO profile; additional clients use the same naming pattern. See [minio/.env.example](minio/.env.example) and [MinIO](minio/README.md). |

Some examples also require direct manifest edits: `VOLUME_PATH`,
`VOLUME_PATH_MYSQL84` and `HOSTNAME_DNS` in local storage manifests, `HOSTNAME_IP`
in `homepage/values.yaml`, and `{HOSTNAME_IP}` in `install-rancher.sh` are literal
markers, not variables loaded from `.env`. Supply actual node paths, names and
service addresses before use. The manual PostgreSQL and pgAdmin Secret examples
also contain empty credential fields; supply their Secrets separately. For the
MySQL example, follow [database setup](databases/mlflow-db/README.md).

## 4. Bootstrap order

1. `./install-k3s.sh` — creates the cluster from `k3s-config.yaml`.
2. `./kube-config.sh` — exports the kubeconfig for the current user.
3. `./get_helm.sh` — Helm client, matching the version in `VERSIONS.md`.
4. `./install-rancher.sh` — management interface (optional; requires Helm).
5. Create the registry pull secret in each namespace (§5).
6. Prepare each component's prerequisites in §1 (namespaces, storage,
   databases, accounts and external services), then use its `deploy.sh`.
   If selecting GlusterFS, follow `glusterfs/README.md` before deploying consumers.
   For an in-cluster S3 endpoint, optionally configure and deploy `minio/` before
   its consumers, then export each consumer's scoped connection settings.
   For Spark, follow [its procedure](spark/README.md): the Spark Operator deployment
   prepares job resources in `spark`; review `spark/submit.sh --render` before
   running the supplied distributed smoke check.
   Configure optional cross-service integrations after their endpoints exist.
7. Verify with the checks in §7.

Rancher is installed as release `rancher` in namespace `cattle-system`.
`install-rancher.sh` creates that namespace when absent using
`helm upgrade --install --create-namespace` and reuses it on subsequent runs;
manual namespace creation is not required. The script also installs cert-manager
in its separate `cert-manager` namespace with the same creation flag. Merely
passing `--namespace cattle-system` selects a namespace without creating it.
See the [Rancher installation procedure](https://ranchermanager.docs.rancher.com/getting-started/installation-and-upgrade/install-upgrade-on-a-kubernetes-cluster)
and [Helm upgrade options](https://helm.sh/docs/v3/helm/helm_upgrade/).

## 5. Credential policy

This repository contains no credential material. Every credential the
stack requires — registry authentication, database passwords, object
storage keys, and the Airflow Fernet key — is either generated at
bootstrap or supplied by the adopter through `.env`, and is never
committed.

`registry/gen-pass.sh` generates the registry credential and writes it
under `registry/registry-creds/`, a path excluded by `.gitignore`. That
directory must never be versioned.

For each namespace that pulls images from the private registry, create
the pull secret from the variables in `.env`:

    kubectl create secret docker-registry regcred \
      --docker-server="$REGISTRY_HOST" \
      --docker-username="$REGISTRY_USER" \
      --docker-password="$REGISTRY_PASSWORD" \
      -n airflow

Use a dedicated service account for image pulls. Do not use an
administrative account.

**Credential history.** An earlier state of this repository contained
deployment credentials. That material has been removed from the working tree
and repository history. Do not reuse credentials from earlier copies of this
repository; generate new values as described above.

## 6. Deployment scope

This repository provides configuration and code to provision the architecture.
Host infrastructure, external databases and identity services must be prepared
by the administrator. Object storage may be external or supplied by the optional
MinIO profile, whose backing storage and built image must be prepared first.
Local checks and template rendering do not
establish that the complete stack has been deployed successfully. See
`VERSIONS.md` for validation limits.

## 7. Verification

To validate the article's actual installer and then the Kubernetes components,
use `python3 scripts/local-smoke.py --plan`, then, on a clean test host/VM,
`sudo bash install-k3s.sh --smoke --components local`. The runner executes `install-k3s.sh`, checks
the native systemd service, node, DNS and NodePort range, then runs sequential
functional checks with synthetic data. K3s provides containerd; image builds run
inside Kubernetes without host Docker. Reports are under ignored `.local-smoke/`.
The native K3s installation is retained, and existing installations are refused.
For a disposable Ubuntu/systemd host using Docker, use
`bash install-k3s.sh --smoke --test-host docker --components local`; this still executes the article
installer inside the test host. Automate all single-host functional checks with
`ALIAS_RUN_K3S_E2E=1 python3 -m unittest discover -s scripts/tests -p test_live_k3s.py -v`.
See
[local smoke checks](scripts/LOCAL_SMOKE.md) for coverage, memory requirements,
component selection, cleanup and explicit validation limits. Unavailable runtime
dependencies and multi-host GlusterFS are reported without claiming success.

Run local version and storage checks from the repository root:

```sh
python3 -m unittest discover -s scripts/tests -p test_versions.py -v
python3 -m unittest discover -s scripts/tests -p test_glusterfs.py -v
```

Install `scripts/requirements.txt` first. Chart rendering also requires local
archives and Helm; see `VERSIONS.md`. After deployment, inspect nodes and pods
with `kubectl get nodes` and `kubectl -n NAMESPACE get pods`, then follow each
component's README for functional checks.

## 8. Replication

**Prerequisites.** Start with the hosts, operating system, capacity and network
access listed in [Requirements](#2-requirements). Install Helm and the Python
requirements in `scripts/requirements.txt` for the deployment tooling; use the
versions recorded in [VERSIONS.md](VERSIONS.md). Prepare a working kubeconfig
for the target cluster and the external databases, object storage, identity
services and persistent storage required by the selected components. Configure
their runtime variables as described in [Required configuration](#3-required-configuration)
and [scripts/README.md](scripts/README.md).

**Bootstrap and dependencies.** Follow [Bootstrap order](#4-bootstrap-order):
initialize K3s, configure client access, install Helm, optionally install Rancher,
prepare any required registry pull Secrets, then deploy the selected components.
Before each component's `deploy.sh`, satisfy its dependencies in the
[component inventory](#1-what-this-repository-contains), including namespaces,
service accounts, RBAC and PVCs where required. If using GlusterFS, provision it
before its storage consumers. If using this repository's OpenSearch for
OpenMetadata, deploy OpenSearch first. Configure optional integrations only after
both endpoints are available. Finish with [Verification](#7-verification) and
the functional checks in each selected component's README.

**Duration.** Local Kubernetes smoke reports record native K3s bootstrap,
component deployment, functional checks and total elapsed time. These timings
describe the selected single-host test, not production or multi-host replication;
see [the smoke procedure](scripts/LOCAL_SMOKE.md) and
[validation limits](VERSIONS.md#configuration-and-verification-limits).
For a replication run, record infrastructure preparation, cluster bootstrap,
component deployment and functional verification separately, plus total elapsed
time. Measure from the start of preparation through completion of the selected
functional checks, recording the selected components, host resources, network
conditions and whether charts and images were already cached. For an individual
deployment, Bash's `time bash mlflow/deploy.sh` reports elapsed time, but readiness
and functional verification must also be timed before reporting replication as
complete. Helm deployment timeouts are limits, not measured durations.

## 9. Reuse and license

Code is released under Apache 2.0. Third-party components keep their own
licenses; see `VERSIONS.md` for the license inventory status.
