# ALIAS Blueprint

Reference implementation of the ALIAS architecture for intelligent
healthcare auditing, as described in:

> The ALIAS Final Blueprint: A Replicable Reference of an Open Architecture for Intelligent Healthcare Auditing
> Raphael Silva Fontes et al.
> Frontiers in Digital Health — Health Informatics, ‹ano›. DOI: ‹DOI do artigo›

- **License:** Apache 2.0 (see `LICENSE`)
- **Citation:** see `CITATION.cff`
- **Artifact DOI:** ‹DOI do Zenodo — preencher após o depósito›
- **Component versions:** see `VERSIONS.md`
- **Status of the reference environment:** decommissioned. See §6.

## 1. What this repository contains

Deployment artifacts of the nine-layer architecture described in the
paper. The inventory below maps each layer to the committed implementation.
Dependencies describe the current deployment configuration; connections marked
optional require explicit configuration. See `VERSIONS.md` for exact releases
and the distinction between this baseline and the study environment.

| # | Layer / component | Repository paths | Provisioning | Dependencies |
|---|---|---|---|---|
| 1 | Infrastructure and security: K3s, Rancher, RBAC | `install-k3s.sh`, `k3s-config.yaml`, `kube-config.sh`, `install-rancher.sh`; component `*/service-account*.yaml` files | Shell installs K3s; Helm installs cert-manager and optional Rancher; `kubectl apply` for RBAC manifests | Host OS and network; cluster access; Helm for Rancher, which uses cert-manager. Component service accounts and role bindings must be applied separately where provided. |
| 2 | Storage: persistent volumes and S3-compatible object storage | `jupyterhub/persistent-volume.yaml`, `airflow/persistent-volume.yaml`, `spark-operator/persistent-volume.yaml`, `registry/persistent-volume.yaml`, `databases/*/deploy.yaml`; persistence settings in component `*/values.yaml` files | `kubectl apply` for static PV/PVC manifests; Helm creates chart-managed PVCs; filesystem and object-store provisioning are external | Existing node paths/mounts for static local PVs; a suitable StorageClass for dynamic claims; an existing S3 endpoint and bucket for MLflow. No GlusterFS cluster or S3 server installer is included. |
| 3 | Processing and AI: Spark, Spark Operator, ETL images | `spark/`, `spark-operator/deploy.sh`, `spark-operator/add-roles.sh`, `spark-operator/database-secrets.yaml`, `spark-operator/persistent-volume.yaml`, `docker-images/pyspark-aws-psql/`, `docker-images/etl-base-image/` | Helm installs the operator and CRDs; shell / `kubectl apply` for service accounts, RBAC and optional storage/Secrets; Dockerfiles build workload images | K3s; service accounts/RBAC; workload images; database, S3 credentials and DAG storage when used by a job. Spark applications, ETL pipelines and trained models must be supplied separately. |
| 4 | Analysis and development: JupyterHub | `jupyterhub/deploy.sh`, `jupyterhub/values.yaml`, `jupyterhub/persistent-volume.yaml`, `jupyterhub/service-account*.yaml`, `jupyterhub/images/hub/` | Helm via `deploy.sh`; `kubectl apply` for namespace, static storage and service account/RBAC; optional custom image build | K3s, Helm, `JUPYTERHUB_*` runtime Secret; existing `nfs-share-pvc`, service account `spark`, and referenced pull secret `regcred`. Spark namespace/RBAC is needed for notebook-submitted Spark workloads. |
| 5 | Workflow orchestration: Airflow | `airflow/deploy.sh`, `airflow/values.yaml`, `airflow/persistent-volume.yaml`, `airflow/image/` | Helm via `deploy.sh`, which prepares namespace and runtime Secrets; optional static PVC / custom image build | K3s, Helm, external metadata database, Fernet and webserver keys. Optional DAG Git source requires an exact commit; optional DAG PVC must exist. Spark integration requires separately supplied DAGs and Spark resources. |
| 6 | Model lifecycle: MLflow tracking and registry | `mlflow/deploy.sh`, `mlflow/values.yaml`, `mlflow/README.md` | Helm via `deploy.sh`, which prepares namespace and runtime Secret | K3s, Helm, existing MySQL database/user and writable S3-compatible bucket/endpoint; `MLFLOW_*` configuration. Neither database nor bucket is created by this script. |
| 7 | Catalog and governance: OpenMetadata | `openmetadata/gen-keys.sh`, `openmetadata/deploy.sh`, `openmetadata/values.yaml`, `openmetadata/README.md` | Shell generates local JWT keys; Helm via `deploy.sh` prepares namespace and Secrets, verifies the chart and pins its test image | K3s, Helm, dedicated PostgreSQL database, OpenSearch endpoint/account, OIDC provider and JWT/Fernet keys. `opensearch/` can supply the search endpoint. MLflow ingestion is optional and separately configured; automatic Airflow pipeline deployment is disabled. |
| 8 | Query: Trino and Apache Pinot | `trino/gen-security.sh`, `trino/deploy.sh`, `trino/values.yaml`, `trino/catalogs.example.json`; `pinot/deploy.sh`, `pinot/values.yaml` | Shell generates Trino authentication/TLS material; separate Helm deployments prepare namespaces, Secrets/policies and workloads | K3s, Helm and a CNI enforcing NetworkPolicy. Trino needs `TRINO_*` credentials and starts with synthetic catalogs; external sources are optional. Pinot needs persistent storage and ZooKeeper (bundled by default). The Trino–Pinot connection is optional. |
| 9 | Visualization: Superset | `superset/deploy.sh`, `superset/values.yaml`, `superset/requirements.lock` | Helm via `deploy.sh`; runtime Secret and hashed Python extension installation during bootstrap; chart-managed Redis | K3s, Helm, existing namespace, external PostgreSQL database/user, `SUPERSET_*` keys and Redis password; persistent storage for Redis. Query-source connections such as Trino must be configured separately. |

All Helm deployments use `scripts/versions.sh`, `versions.lock.json`,
`versions/*.values.json` and `scripts/locked-images.py`. Runtime configuration
and Secret creation use `scripts/env.sh`, `scripts/runtime.sh` and
`scripts/runtime-secrets.py` where invoked; install `scripts/requirements.txt`
in that Python environment. See `scripts/README.md` for per-component behavior.

The storage manifests contain `local.path` and node-affinity placeholders that
must be adapted before use. Names such as `nfs-share-pv` do not provision an NFS
server or a shared filesystem: the manifests declare local volumes. The study's
GlusterFS topology in §2 is historical context; its installation is not automated
here. Chart deployments do not apply the separate static PV/PVC files.

Supporting components are outside the nine-layer numbering:

| Component | Repository paths | Provisioning | Dependencies |
|---|---|---|---|
| Private registry | `registry/` | Shell generates htpasswd and pull Secrets; Helm deploys the registry; separate PVC manifest | Existing namespace and `docker-registry-pv-claim`; storage and registry credentials. Optional when only public images are used, subject to component pull-secret settings. |
| Database examples: PostgreSQL and MySQL | `databases/namespace.yaml`, `databases/prod-db/deploy.yaml`, `databases/superset-db/deploy.yaml`, `databases/mlflow-db/deploy.yaml` | Manual configuration and `kubectl apply` | Node paths, namespace and freshly supplied database credentials. Application deploy scripts do not apply these examples or create their external databases. |
| Database administration: pgAdmin | `pgadmin/` | `deploy.sh` applies Secret, Deployment and Service manifests | Existing namespace, supplied login Secret and separately configured database connections. |
| Landing page: Homepage | `homepage/` | Helm via `deploy.sh` | Existing namespace; service URLs configured in `values.yaml`. |
| Search backend: OpenSearch | `opensearch/` | Shell generates TLS/security material; Helm via `deploy.sh` | Persistent storage and `OPENSEARCH_*` credentials. Independently deployable; consumers configure their own endpoint/account. |
| Image build recipes | `docker-images/`, `airflow/image/`, `jupyterhub/images/hub/` | Manual container builds from Dockerfiles and dependency locks | Container build tooling and artifact access; a registry accessible to workloads for custom images. Builds are not invoked by component deployment scripts. |

## 2. Requirements

- Base operating system: any distribution with a supported container
  runtime. The reference cluster ran Ubuntu 20.04 LTS (VMware virtual
  machines, x86_64, kernel 5.4.0-216-generic); the independent
  redeployment reported in the paper was performed on Rocky Linux 9.x.
- Hardware for the reference footprint: 4 nodes, 16 vCPU and 24 GB of
  RAM per node, 2 TB of storage per node (8 TB aggregated, approximately
  4 TB usable under the GlusterFS distributed-replicated volume with
  replication factor 2).
- CPU-only. No GPU or TPU is required for the baseline ETL, training,
  or inference workloads (criterion 3 of the technology admission
  checklist).
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
| ‹demais variáveis extraídas dos manifestos› | |

## 4. Bootstrap order

1. `./install-k3s.sh` — creates the cluster from `k3s-config.yaml`.
2. `./kube-config.sh` — exports the kubeconfig for the current user.
3. `./get_helm.sh` — Helm client, matching the version in `VERSIONS.md`.
4. `./install-rancher.sh` — management interface (optional; requires Helm).
5. Create the registry pull secret in each namespace (§5).
6. Prepare each component's prerequisites in §1 (namespaces, storage,
   databases, accounts and external services), then use its `deploy.sh`.
   Configure optional cross-service integrations after their endpoints exist.
7. Verify with the checks in §7.

Expected duration for the full footprint on four nodes: ‹preencher›.

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

**Pre-release history.** An earlier state of this repository contained
credential material generated during deployment of the reference
environment. That material has been removed from the working tree and
from the repository history. The reference environment described in the
paper has been decommissioned and the authors no longer hold operational
access to it, so the authors cannot confirm whether any credential
issued for that environment remains active. Do not reuse any credential
found in the pre-release history of this repository; generate new values
as described above.

## 6. Status of the reference environment

The four-node reference cluster has been decommissioned. The results
reported in the paper refer to that environment and to the independent
redeployment performed during the study. No further measurement or
deployment can be offered from this artifact. What the repository
provides is the specification and the code required for a third party to
provision the architecture independently.

## 7. Verification

‹listar apenas o que foi de fato executado durante o estudo:
`kubectl get nodes`, `kubectl -n ‹ns› get pods`, e a consulta de fumaça
de cada camada. Nada que não tenha rodado.›

## 8. Reuse and license

Code is released under Apache 2.0. Third-party components keep their own
licenses, listed in `VERSIONS.md`. The manuscript is distributed under
the terms of ‹política do periódico›.
