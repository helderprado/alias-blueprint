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
| 6 | Model lifecycle: MLflow tracking and registry | `mlflow/deploy.sh`, `mlflow/values.yaml`, `mlflow/README.md` | Helm via `deploy.sh`, which prepares namespace and runtime Secret | K3s, Helm, existing MySQL database/user and writable S3-compatible bucket/endpoint; `MLFLOW_*` configuration. Neither database nor bucket is created by this script. |
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
| Database examples: PostgreSQL and MySQL | `databases/namespace.yaml`, `databases/prod-db/deploy.yaml`, `databases/superset-db/deploy.yaml`, `databases/mlflow-db/deploy.yaml` | Manual configuration and `kubectl apply` | Node paths, namespace and freshly supplied database credentials. Application deploy scripts do not apply these examples or create their external databases. |
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

No credential is versioned in this repository. Copy `.env.example` to
`.env` and fill in every variable listed there. The bootstrap scripts
abort with an explicit message when a required variable is missing.

| Variable | Purpose |
|----------|---------|
| `K3S_VERSION` | Pinned version used by `install-k3s.sh` |
| `K3S_CONFIG` | Path to `k3s-config.yaml` |
| `REGISTRY_HOST` | Host and port of the private registry |
| `REGISTRY_USER` | Registry user; must not be an administrative account |
| `REGISTRY_PASSWORD` | Registry password, supplied at runtime |
| `GLUSTERFS_NODES`, `GLUSTERFS_NFS_SERVER`, `GLUSTERFS_CLIENT_CIDRS` | Optional storage topology and trusted clients; see `glusterfs/.env.example` |
| ‹demais variáveis extraídas dos manifestos› | |

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
`sudo bash install-k3s.sh --smoke`. The runner executes `install-k3s.sh`, checks
the native systemd service, node, DNS and NodePort range, then runs sequential
functional checks with synthetic data. K3s provides containerd; image builds run
inside Kubernetes without host Docker. Reports are under ignored `.local-smoke/`.
The native K3s installation is retained, and existing installations are refused. See
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

**Duration.** No end-to-end replication duration has been measured for this
repository; the existing validation covers local checks and chart rendering,
as detailed in [VERSIONS.md](VERSIONS.md#configuration-and-verification-limits).
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
