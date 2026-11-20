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
paper. Each layer of the paper's Table 4 maps to a path below.

| # | Layer | Component | Path | Provisioned by |
|---|-------|-----------|------|----------------|
| 1 | Infrastructure and security | K3s, Rancher, RBAC | `install-k3s.sh`, `k3s-config.yaml`, `kube-config.sh`, `install-rancher.sh` | shell script |
| 2 | Storage | ‹preencher› | ‹preencher› | ‹helm / manifest› |
| 3 | Processing and AI | Spark, Spark Operator | `spark/`, `spark-operator/` | helm / manifest |
| 4 | Analysis and development | JupyterHub | `jupyterhub/` | helm |
| 5 | Workflow orchestration | Airflow | `airflow/` | helm |
| 6 | Model lifecycle | MLflow | `mlflow/` | helm |
| 7 | Catalog and governance | OpenMetadata | `openmetadata/` | helm |
| 8 | Query | Trino, Apache Pinot | `trino/`, `pinot/` | helm |
| 9 | Visualization | Superset | `superset/` | helm |

Supporting directories, not part of the nine layers: `registry/`
(private image registry), `pgadmin/` (database administration),
`homepage/` (landing page), `docker-images/` (image build recipes),
`opensearch/` (independent persistent search service).

## 2. Requirements

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
- `kubectl` ‹versão› and `helm` ‹versão›.
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
3. `./install-rancher.sh` — management interface (optional).
4. `./get_helm.sh` — Helm client, matching the version in `VERSIONS.md`.
5. Create the registry pull secret in each namespace (§5).
6. `helm install` the components in the order of the §1 table, storage
   before processing.
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
