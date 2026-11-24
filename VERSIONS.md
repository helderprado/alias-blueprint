# Version inventory and reproducibility baseline

This baseline records the versions selected for
deployment with this repository. Validation performed locally is described below.

`versions.lock.json` records the exact chart releases, official index URLs,
package SHA-256 values, and verified container image digests. Deployment scripts
read committed chart versions through `scripts/versions.sh`; no release channel
is queried to choose a version. Explicit K3s/Airflow/Helm version overrides remain
possible, but they must name exact releases; changing the baseline requires
reviewing the corresponding image and dependency locks as well.

## Platform and tools

| Item | New baseline / recorded evidence | Source |
|---|---|---|
| Host OS | Ubuntu 22.04 LTS, amd64, chosen deployment prerequisite; host installation is outside this repo | `versions.lock.json: host_baseline` |
| K3s | `v1.34.13+k3s1`, default fixed release | `install-k3s.sh` |
| kubectl | K3s-bundled Kubernetes client, tied to the selected K3s distribution; no standalone client installer in this repo | `install-k3s.sh`, `kube-config.sh` |
| Helm | `v3.17.3`; installer accepts only an exact stable release, never an implicit newest release | `get_helm.sh` |
| Tool dependencies | `PyYAML==6.0.3`, `bcrypt==4.3.0` | `scripts/requirements.txt` |
| Optional shared storage | GlusterFS `10.1-1ubuntu0.2`, NFS-Ganesha / FSAL_GLUSTER `3.5-1ubuntu1`, NFS client `1:2.6.1-1ubuntu1.2`; Ubuntu 22.04 amd64 host packages | `versions.lock.json: glusterfs`, `glusterfs/` |
| Python for standalone tools / ETL | `3.11.11`; ETL base is the verified digest of `python:3.11.11-slim-bookworm` | `versions.lock.json`, `docker-images/etl-base-image/Dockerfile` |
| Container OS / bundled interpreters | Inherited from immutable image digests below. Container OS labels do not identify the host OS or kernel. Interpreter patch versions not exposed by manifests are not recorded. | Dockerfiles and image lock |

## Helm charts

All entries were confirmed in their publishers' chart indexes. Chart packages
were downloaded to temporary storage and checked against index SHA-256 values.

| Component | Chart release | Chart appVersion | Official index |
|---|---|---|---|
| trino | `1.45.0` | `484` | [index](https://trinodb.github.io/charts/index.yaml) |
| Apache Pinot | `1.0.0` | `1.0.0` | [index](https://raw.githubusercontent.com/apache/pinot/master/helm/index.yaml) |
| OpenSearch | `2.32.0` | `2.19.1` | [index](https://opensearch-project.github.io/helm-charts/index.yaml) |
| OpenMetadata | `2.0.9` | `2.0.9` | [index](https://helm.open-metadata.org/index.yaml) |
| Apache Airflow | `1.16.0` | `2.10.5` | [index](https://airflow.apache.org/index.yaml) |
| cert-manager | `v1.13.3` | `v1.13.3` | [index](https://charts.jetstack.io/index.yaml) |
| Homepage | `2.1.0` | `v1.2.0` | [index](https://jameswynn.github.io/helm-charts/index.yaml) |
| JupyterHub | `3.2.1` | `4.0.2` | [index](https://jupyterhub.github.io/helm-chart/index.yaml) |
| MLflow | `1.11.7` | `3.16.0` | [index](https://community-charts.github.io/helm-charts/index.yaml) |
| Rancher | `2.15.3` | `v2.15.3` | [index](https://releases.rancher.com/server-charts/stable/index.yaml) |
| Private registry | `2.2.3` | `2.8.1` | [index](https://twuni.github.io/docker-registry.helm/index.yaml) |
| Spark Operator | `1.3.2` | `v1beta2-1.5.0-3.5.0` | [index](https://kubeflow.github.io/spark-operator/index.yaml) |
| Apache Superset | `0.14.2` | `4.1.2` | [index](https://apache.github.io/superset/index.yaml) |

Each deployment passes `--version` and a committed `versions/*.values.json`
override. These image overrides pin hooks as well as normal workloads, because
Helm post-rendering alone does not cover hooks. `scripts/locked-images.py` adds a
strict check for other rendered image fields and refuses unknown floating tags.
Install the exact tool dependency with `python3 -m pip install -r scripts/requirements.txt`
before deployment. The optional Superset websocket service stays disabled;
enabling it requires adding a verified immutable image to the baseline.

## Images

The following tags are lookup provenance only. Executed manifests and Dockerfiles
use the corresponding SHA-256 digest, including tags originally specified only
by a major version or OS family. A digest fixes bytes even when a publisher moves
a tag. Digests do not imply vulnerability, compatibility, or license review.

| Source reference | Immutable reference |
|---|---|
| `trinodb/trino:484` | `trinodb/trino@sha256:2704eb53935af5e582d63d6033e9bf99d20c325e9b0e30b1016ef59a4773979f` |
| `apachepinot/pinot:1.4.0` | `apachepinot/pinot@sha256:c7372d4099af6756a17128ea95d91fe415080dfe1138b4b00bf61feea26eff84` |
| `zookeeper:3.9.3` | `zookeeper@sha256:9980cafbff742c15b339811ae829faa61c69154606ec504223560da9d31acd43` |
| `opensearchproject/opensearch:2.19.1` | `opensearchproject/opensearch@sha256:72fe2fc84be8295906b8efca020b46c58ed45c8da60cd9b8b49e1991e38e89a4` |
| `docker.getcollate.io/openmetadata/server:2.0.9` | `docker.getcollate.io/openmetadata/server@sha256:8575ad1b61866f76075f096c40ec4e9ee19339dcab50169adec9b69bec380f98` |
| `apache/airflow:2.10.5-python3.11` | `apache/airflow@sha256:b16e19f925ae0dcabaa2271b37212891ed68bf74e26c2db61f46dddd7d502937` |
| `apache/superset:4.1.2` | `apache/superset@sha256:15e110b8533d3cb6a0d529512ea71252b0ac62e3f72b1f7a5000f1361822ac26` |
| `apache/superset:dockerize` | `apache/superset@sha256:afe59523a6c8774c3b16d0f44146b2e52f327a7d26a47b4cc63b904fcdedf057` |
| `bitnamilegacy/redis:7.0.10-debian-11-r4` | `bitnamilegacy/redis@sha256:224a79826b42869bdc72a70933efd840c5a5f10a70caafca68e57be6901e36fb` |
| `burakince/mlflow:3.16.0` | `burakince/mlflow@sha256:ab4b566644b90f00f7baf024ab4255e8219a6eeb530f34dd996fd0b0769c5fe1` |
| `busybox:1.38.0` | `busybox@sha256:a46257e06c82ad85242d0d38077d0a52d9896389ca60a1a59d3463db586e5fa4` |
| `docker.io/bitnami/redis:7.0.10-debian-11-r4` | `bitnamilegacy/redis@sha256:224a79826b42869bdc72a70933efd840c5a5f10a70caafca68e57be6901e36fb` |
| `docker.io/kubeflow/spark-operator:v1beta2-1.5.0-3.5.0` | `docker.io/kubeflow/spark-operator@sha256:e229fe76dfd5563d90a8ab4f67c3ab034813cc4dee10b256fb8e33935bbca456` |
| `dpage/pgadmin4:9.3` | `dpage/pgadmin4@sha256:bd71932cb1ef94719e783f0eed42c227bc67877a7c7e076c7092738711e5f4d4` |
| `ghcr.io/benphelps/homepage:v0.7.0` | `ghcr.io/benphelps/homepage@sha256:079d9db37c4ef6f815cc107ce0137dad05a37beaf5acc52288b420de3a788122` |
| `httpd:2.4-alpine` | `httpd@sha256:32bd0639bcc4917ef1fd9363a1d9dd2dd9c498565118b062a10d51e43a5c3a24` |
| `jupyter/all-spark-notebook:python-3.11` | `jupyter/all-spark-notebook@sha256:b63bae2d9d34779ac969deeb4834efd838991f77269ca9a76bf6b0d1f8678d29` |
| `jupyterhub/k8s-hub:3.2.1` | `jupyterhub/k8s-hub@sha256:1f8db66b29c597d4a26ec9eef08df4472e896a64f50739d5f242a9c18dd43e3c` |
| `mysql:8.4.7` | `mysql@sha256:0426ec38c7a10aa45ba383887df7878f74ee70e2fd589c7b69207f3577901903` |
| `postgres:13-alpine` | `postgres@sha256:fb9065b6e3e213bdc07edd372a5b2a26245840b7fb65d1fd8b6700106d51805c` |
| `postgres:14` | `postgres@sha256:c0e9c0e9bac7e4c1834b698217a03ee5c708de30d313c84a506972de0e24b059` |
| `python:3.11.11-slim-bookworm` | `python@sha256:081075da77b2b55c23c088251026fb69a7b2bf92471e491ff5fd75c192fd38e5` |
| `quay.io/jetstack/cert-manager-cainjector:v1.13.3` | `quay.io/jetstack/cert-manager-cainjector@sha256:ac5154525f99bd0872671613741aac1b7dcb9c0df988571a7618155ddb6fabd2` |
| `quay.io/jetstack/cert-manager-controller:v1.13.3` | `quay.io/jetstack/cert-manager-controller@sha256:2121d4250f5734ee097df243507d06536fc264140dba3425045a825ef597c79d` |
| `quay.io/jetstack/cert-manager-ctl:v1.13.3` | `quay.io/jetstack/cert-manager-ctl@sha256:d0d12f721e01b19973c989646c96905bfca7a0ea5f7888d5e9b4adabb4fbc56c` |
| `quay.io/jetstack/cert-manager-webhook:v1.13.3` | `quay.io/jetstack/cert-manager-webhook@sha256:f45b21f770bf4676c732f19e2ef17c34f46ac75873a5e0aa25703d808b2e5566` |
| `quay.io/jupyterhub/configurable-http-proxy:4.6.1` | `quay.io/jupyterhub/configurable-http-proxy@sha256:fd916f75415f1e7e813c5a18b34a6042a601604938ff8777b044447efb3bd819` |
| `quay.io/jupyterhub/k8s-hub:3.2.1` | `quay.io/jupyterhub/k8s-hub@sha256:2528c6e575870c00fb03045520f7b3786a0a016889413769bdd33eec98826bf1` |
| `quay.io/jupyterhub/k8s-image-awaiter:3.2.1` | `quay.io/jupyterhub/k8s-image-awaiter@sha256:f65b644ed6db2af65cdefe449ea07242df7995e9ed3a047928ff7f47cc8485b6` |
| `quay.io/jupyterhub/k8s-network-tools:3.2.1` | `quay.io/jupyterhub/k8s-network-tools@sha256:e532a2dc4761685cedc87d4c0df864b8b1fad45f4dd54535b1b5dff23897d870` |
| `quay.io/prometheus/statsd-exporter:v0.26.0` | `quay.io/prometheus/statsd-exporter@sha256:a3924f9429c8237293336ff40c5a246238ff9f64aaf712521b2d29f45d6214d5` |
| `rancher/rancher:v2.15.3` | `rancher/rancher@sha256:3f3a50c6e49c1cf5b4673bef236e0f260f36055de4d073438e38c441dc97aa9b` |
| `rancher/shell:v0.8.3` | `rancher/shell@sha256:abb0804d239cae9c137347b0c1175e745ab791d60023ae619f6aa6465fb2da7c` |
| `registry.k8s.io/git-sync/git-sync:v4.1.0` | `registry.k8s.io/git-sync/git-sync@sha256:fd9722fd02e3a559fd6bb4427417c53892068f588fc8372aa553fbf2f05f9902` |
| `registry.k8s.io/kube-scheduler:v1.26.11` | `registry.k8s.io/kube-scheduler@sha256:0684e23172d920314971580ab115a5b679ac1fae2cb94d83e9105c0b1e93a1bc` |
| `registry.k8s.io/pause:3.9` | `registry.k8s.io/pause@sha256:7031c1b283388d2c2e09b57badb803c05ebed362dc88d84b480cc47f72a21097` |
| `registry:2.8.1` | `registry@sha256:dbaa3e69f563fc146f3337eb9de422f74f6765bf0203c891ddfbd74a6f9b56eb` |
| `spark:3.5.0-scala2.12-java17-python3-ubuntu` | `spark@sha256:edc304196cbd7619933658d6e01b082b12bcef45ba96223d4a56584c0b4b1fcf` |
| `spark:3.5.0-scala2.12-java17-ubuntu` | `spark@sha256:1c72a3d4f0a9634f09bc0d7d6a2fc03653b0bfbb9f34bca2ddf0a4a726abbd49` |

The unused private image for JupyterHub's Hub was replaced with the locked
official image; the existing Kubernetes hook uses its `kubernetes_asyncio` client.
Custom Dockerfiles for JupyterHub's Hub and Airflow remain available but are not
the default deployed images.
Spark's base now explicitly includes Python. Its recipe no longer downloads
Python through a moving PPA, upgrades pip/setuptools, or copies absent local
PySpark directories. Existing Maven artifact versions remain explicit:
AWS SDK `1.12.262`, PostgreSQL JDBC `42.1.1`, Hadoop `3.3.4`.

## Python dependencies

Application extensions use transitive locks with exact `==` versions and artifact
hashes. Pip calls use `--no-deps --require-hashes --only-binary=:all:` so they do
not select additional dependency or source-build tool versions during execution.
Airflow's lock was resolved with the official `constraints-2.10.5/constraints-3.11.txt`;
a copy is in `airflow/image/constraints-3.11.txt`. Superset's extension lock targets
Python 3.10; the other application locks target Python 3.11.

| Consumer | Lock file | Exact package pins | Lock SHA-256 |
|---|---|---|---|
| ETL | `docker-images/etl-base-image/requirements.txt` | 8 | `12cfd4ee6e21515fcae24311bbd24f4cc892eb77500e78a4fa4de1b1f1142576` |
| Custom JupyterHub Hub | `jupyterhub/images/hub/requirements.txt` | 28 | `65ff314c98c9985f990ad6a9b32666d9ec47325f0ce6c2d847415a196ba1c7db` |
| Custom Airflow | `airflow/image/requirements.txt` | 171 | `5088606e28b89fa62138ab836f9d334d50c8b29d87fd5ab04a92fc43084f3bcc` |
| Superset extensions | `superset/requirements.lock` | 15 | `eda761cd52efd1abe6f6d7c067355340815bab3e5d414d1a57075931b9de7be7` |

Superset mounts the identical lock as `extraConfigs.requirements.lock` and uses
it during bootstrap. Python code already baked into locked upstream images is
fixed by the image digest rather than re-resolved by our scripts. Regenerating a
lock is a deliberate maintenance action, not part of deployment.

## Repository audit

The inventory was compared with the committed manifests, Dockerfiles, installers
and locks: **13 charts, 39 source-image mappings (38 distinct immutable image
references), and four application Python locks**. Every chart/image table entry
and each Python package count and lock-file SHA-256 above matches its source.
The nine-layer component/path/provisioning/dependency inventory is in `README.md`.
From the repository root, inspect the declared versions without querying a
release service:

```sh
# K3s / Helm defaults and exact-release validation.
rg -n 'K3S_VERSION=|INSTALL_K3S_VERSION|DESIRED_VERSION=|TAG=' install-k3s.sh get_helm.sh
# Chart releases, application versions, host OS prerequisite and Python target.
rg -n '"(helm|k3s|version|appVersion|host_baseline|distribution|architecture|python_tools)"' versions.lock.json
# Image inputs and committed digest overrides; split image fields need the overrides.
rg -n '(^FROM |^ARG base_img=|image:|name:|repository:|tag:|@sha256:)' \
  -g Dockerfile -g '*.yaml' -g '*.json' -g '!airflow/repo/index.yaml' \
  jupyterhub airflow docker-images databases pgadmin versions \
  spark-operator trino pinot opensearch openmetadata mlflow superset registry homepage
# Application and tool dependency pins.
rg -n '^[A-Za-z0-9_.-]+(\[[^]]+\])?==' \
  scripts/requirements.txt docker-images/etl-base-image/requirements.txt \
  jupyterhub/images/hub/requirements.txt airflow/image/requirements.txt superset/requirements.lock
```

The following check found **zero** floating `latest` image tags in the repository's
manifest, image-override, installer, Dockerfile and example-configuration sources:

```sh
if rg -n '(:latest\b|\btag["\x27]?[[:space:]]*:[[:space:]]*["\x27]?latest\b)' \
  -g '*.yaml' -g '*.yml' -g '*.json' -g '*.sh' -g Dockerfile -g '*.example' .; then
  echo 'FAIL: floating latest tag found' >&2
  exit 1
else
  status=$?
  if [ "$status" -ne 1 ]; then exit "$status"; fi
  echo 'PASS: latest image tags = 0'
fi
```

Text searches alone cannot establish effective Helm images: chart defaults,
hooks and values merge together. The existing version tests were also run with
all 13 cached chart archives and a local Helm binary, without network or cluster
access. All three tests passed, including archive SHA-256 checks, rendered
container/hook digest checks, rejection of unknown floating images and Python
lock/Superset bootstrap consistency. To repeat with locally available archives
named `COMPONENT.tgz` and the synthetic runtime overrides where needed:

```sh
ALIAS_CHARTS_DIR=/path/to/verified-charts ALIAS_HELM=/path/to/helm \
  python3 -m unittest discover -s scripts/tests -p test_versions.py -v
```

Without both environment variables, the chart-rendering test is skipped. The
audit validates the selected versions in repository deployment defaults. Host
installation is external; the tools' Python target is recorded but not enforced
by a Python installer. The K3s bootstrap script is downloaded from `get.k3s.io`
and is not itself content-pinned, although the installed K3s release is exact.
Explicit administrator overrides and user-submitted workloads need their own review.

## Configuration and verification limits

Entry scripts load the repository-root `.env` with `scripts/env.sh`; an exported
`ALIAS_ENV_FILE` selects another trusted Bash file. File assignments override
exports. Required credentials are validated before external Secrets and Helm are
invoked. See `scripts/README.md`.

Initial verification covered chart renders, hook/container image digests,
Python lock structure, shell syntax and mocked tests. The opt-in live smoke
procedure now executes the actual `install-k3s.sh` in a pinned Ubuntu 22.04
systemd Docker test host, then installs real Kubernetes services and performs
cross-service operations. Its reports distinguish PASS, FAIL, BLOCKED and NOT_RUN;
they record installer/configuration hashes, versions and individual durations.
The automated live test also verifies every selected component result and host disposal.
Run `20261123T193921Z-1c7f74` passed all 17 local functional stages and cleanup
with a fresh K3s installation; the enclosing automated test took about 29 minutes
with the Ubuntu test-host image and public charts cached. Per-stage results and
timing boundaries are recorded in the local smoke procedure.
See [local smoke procedure](scripts/LOCAL_SMOKE.md); successful offline tests
alone still do not establish live deployment success.

The smoke profile builds the committed MinIO and Spark S3 recipes with pinned
BuildKit `v0.20.2`, and uses pinned MySQL `8.4.7` on its own fresh PVC because
MLflow model retrieval/listing requires window functions absent in MySQL 5.7.
The MLflow database example uses the same MySQL 8.4.7 image, explicit `MYSQL_*`
Secret references and trigger-creation setting. Its 8.4 PV/PVC names are separate
from the old 5.7 storage; existing data is not automatically migrated. The smoke
runner now reads that committed Deployment rather than generating another server
definition. Other custom image
recipes, production load/HA, external OIDC, JDBC and multi-host NFS/GlusterFS
are outside this live profile. Resumed test timings are not fresh replication
measurements. The Docker host shares the Docker VM kernel and is not a separate
machine/VM validation. The cert-manager ACME solver uses the exact release
`v1.13.3` inherited from the pinned chart; its digest was not separately queried.
External databases, storage, registry permissions and host provisioning remain
prerequisites for ordinary component deployments. A
future Rancher-managed cluster or user-submitted Spark workload is outside this
set of manifests and needs its own lock review.

## Third-party licenses

The blueprint is Apache-2.0. Third-party components retain their licenses. A full
component-by-component license inventory has not been verified by this version
inventory and remains pending; image pins are not a legal license inventory.

## OpenMetadata addition

The catalog server uses official chart/application `2.0.9` and a committed image
digest, added after the original baseline. Its chart package SHA-256 was checked.
The image digest was obtained from public manifest metadata after an anonymous
pull limit; the full image was not downloaded or run. PostgreSQL, OpenSearch and
OIDC are external prerequisites, not silently provisioned dependencies. Ingestion
deployment of OpenMetadata ingestion DAGs through Airflow is disabled; adding MLflow catalog ingestion requires its
explicit connector workflow as described in `openmetadata/README.md`.

OpenMetadata's upstream Helm test contains an unversioned busybox image. Its deploy
verifies the downloaded original chart hash, then patches only that test image to
the existing busybox digest in `versions.lock.json`. The temporary chart is used
for install/upgrade and discarded on exit; no vendored default credentials are
committed. See `scripts/prepare-openmetadata-chart.py`.

## OpenSearch backend addition

The independent OpenSearch service now has chart `2.32.0`, server `2.19.1`, immutable server
and busybox init-image pins, a persistent single-node footprint and explicit TLS
and internal-account bootstrap. The official chart package SHA-256 was checked;
the server digest was read from its manifest metadata without pulling/running it.
See `opensearch/README.md` for deployment and configuration.

## Independent service configuration

OpenSearch consumes only `OPENSEARCH_*` variables. Its generic bootstrap client
account is optional and supports explicit index scopes. OpenMetadata has a separate
search endpoint, account and truststore configuration and may use an external
service. Airflow consumes its own `AIRFLOW_*` settings, creates its namespace and
starts without a private DAG repository or pre-existing DAG claim. DAG Git delivery
is optional and requires an explicit commit. This configuration change does not
change any pinned application, chart or image version.

## Independent query services

Trino uses official chart `1.45.0` and image `484`. Pinot's official chart reports
`appVersion: 1.0.0` but defaults to a nightly image; this deployment explicitly
selects and locks Pinot `1.4.0` and ZooKeeper `3.9.3`. Trino 484's documented Pinot
connector requires Pinot 1.1.0 or higher. The example connection is optional and
uses broker-only queries. Chart hashes and image digests were checked against
publisher metadata. The local live profile ingests three rows into Pinot, checks
the broker result, and queries the same table through authenticated TLS Trino.

Trino has a local password/TLS bootstrap. Pinot uses a private single-tenant HTTP
profile restricted by NetworkPolicy, not application authentication/TLS. Neither
service requires OpenMetadata or another query service to deploy. See their own
README and `.env.example` files for access and persistence limits.

Trino deployment verifies the official chart SHA-256 and excludes only the
upstream CI connection-test template, whose demo credentials/certificate names
do not match this authenticated profile. Application templates are unchanged.
See `scripts/prepare-trino-chart.py`; the administrator SQL smoke query is in its README.

## GlusterFS storage profile

`glusterfs/install-node.sh` installs the exact host package revisions recorded
under `glusterfs.packages`, including the matching GlusterFS libraries. These
revisions were checked against official Ubuntu package metadata: [GlusterFS](https://packages.ubuntu.com/jammy-updates/glusterfs-server),
[NFS-Ganesha](https://packages.ubuntu.com/jammy-updates/nfs-ganesha),
[FSAL_GLUSTER](https://packages.ubuntu.com/jammy-updates/nfs-ganesha-gluster) and
[NFS client](https://packages.ubuntu.com/jammy-updates/nfs-common). Installers
fail when a pinned package is unavailable and refuse downgrades. Additional OS
dependencies are resolved by the host's APT repositories; this is a component
package lock, not a complete OS snapshot.

The optional volume/export/PV scripts use NFSv4.1 and the standard Kubernetes
NFS volume source. They add no chart or container image and do not use the
removed GlusterFS Kubernetes volume driver. Three replicas are the default;
one node is an explicit development option. Consumer defaults and the existing
chart/image locks remain unchanged until the administrator selects this profile.

Offline tests cover configuration validation, generated PV/claim bindings,
NFS access restrictions, rejection of conflicting/unmanaged resources before
writes, existing-volume reuse, and inventory failure handling. No package
installation, GlusterFS cluster, NFS mount, workload I/O or failover has been run
for this addition. Gateway high availability and data migration are outside
this profile. See `glusterfs/README.md` for provisioning and verification.

## Optional MinIO source-built profile

`minio/chart/` is a local Apache-2.0 chart, version `0.1.0`, separate from the
13 downloaded upstream charts above. The Community server is
`RELEASE.2025-10-15T17-29-55Z` at commit
`9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`; the client is
`RELEASE.2025-08-13T08-35-41Z` at commit
`7394ce0dd2a80935aded936b09fa12cbb3cb8096`. Both retain AGPLv3; this does not
change the license of the blueprint's original scripts/chart. The server
repository was archived April 25, 2026; continued maintenance is not claimed.
See [MinIO licensing, source retention and primary sources](minio/README.md).

The official chart index was inspected (chart `5.4.0`, package SHA-256
`25fa2740480d1ebc9e64340854a6c42d3a7bc39c2a77378da91b21f144faa9af`), but that
chart defaults to a December 2024 server image. It is not installed by this
profile. The local chart supplies dedicated persistent storage, health probes,
NetworkPolicy and bucket-scoped bootstrap accounts without inheriting that image.
The October 2025 server release includes a session-policy security fix and
instructs administrators to build containers from source.

`versions.lock.json: minio` records both downloaded source archives' SHA-256
values, verified tag-to-commit mappings, the Go `1.24.8-bookworm` builder digest,
and the existing Python `3.11.11-slim-bookworm` runtime digest. `minio/Dockerfile`
checks the source archives and Go modules and retains corresponding sources and
license files. No output-image digest is invented: deployment requires
`MINIO_IMAGE` with the actual digest of the administrator's built and published image.
Server and bootstrap jobs use that same immutable image.

Offline validation covers both PVC modes and HTTP/TLS chart rendering, credential
separation and refusal of changed credentials, migration guards, restricted
bucket policies, private connection exports and the interactive wizard. Use:

```sh
ALIAS_HELM=/path/to/helm python3 -m unittest discover -s scripts/tests -p test_minio.py -v
```

The live smoke profile has built and run this image, provisioned scoped accounts,
and verified object upload/download/delete plus consumer Spark/MLflow operations.
Its actual image digest and per-stage outcomes are retained in private run
artifacts. Production workload sizing, storage failover and multi-host durability
are not established by those operations. Helm rollback cannot undo bucket/IAM state.

## Spark workload standardization

The existing Spark `3.5.0` image and Spark Operator chart `1.3.2` are retained. The
Spark Operator now watches only `spark`, uses its admission webhook, has explicit
resources, and verifies the chart archive before installation. Chart-created
workload accounts/RBAC are disabled; `spark/setup.sh` applies explicit namespace
RBAC, a shared job resource budget and optional immutable runtime Secrets. The
controller's upstream cluster permissions remain separate from driver permissions.

`docker-images/pyspark-aws-psql/jars.lock.json` records SHA-256 for AWS SDK
`1.12.262`, Hadoop AWS `3.3.4` and PostgreSQL JDBC `42.1.1`. All three JAR downloads
were checked against Maven Central's published SHA-1 values before recording
SHA-256. The recipe enforces those SHA-256 values and requires the base's matching
Hadoop client API/runtime `3.3.4` rather than adding another `hadoop-common` JAR.
Artifact versions were not upgraded or separately audited for vulnerabilities.

The bounded example `SparkApplication` uses a ConfigMap with synthetic PySpark
code and optional Secret references/S3A configuration, plus an optional read-only
PVC in `spark`. The GlusterFS `spark` profile adds a namespaced claim for existing
DAG exports without changing or deleting legacy `spark-operator` claims. MinIO
is accessed through a scoped S3 account, never its data PVC.

Offline checks cover rendered workload credentials/resources, failure before
writes, old global binding detection, changed credential refusal, existing-job
protection, shared-claim configuration, rejection of corrupt JARs, the actual
chart with hook digests, and fields supported by its pinned CRD. Run:

```sh
ALIAS_HELM=/path/to/helm ALIAS_SPARK_OPERATOR_CHART=/path/to/spark-operator-1.3.2.tgz \
  python3 -m unittest discover -s scripts/tests -p test_spark.py -v
```

The live smoke profile has built the S3/JDBC-capable image and run distributed
Spark computations with a real MinIO Parquet round trip, including submissions
from Airflow and a JupyterHub-spawned notebook Pod. JDBC and NFS round trips,
workload benchmarks and production scaling remain unverified. See
[Spark](spark/README.md) for the complete procedure and resource/isolation limits.
