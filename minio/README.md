# Optional MinIO S3 service

This independent Helm release provides an S3 endpoint for MLflow and other
clients. It needs no MLflow, Airflow, database or GlusterFS deployment. Existing
external S3 services remain supported; consumers opt in by configuring their own
endpoint, bucket and account. The initial profile is a **single server with one
dedicated PVC**, not a distributed or highly available object store.

## Versions, licensing and maintenance

The blueprint's own scripts and chart remain Apache-2.0. The separately running
MinIO Community server and `mc` client retain their upstream AGPLv3 licenses;
the blueprint license does not relicense those programs. They communicate with
consumers through S3 rather than incorporating their code into applications.

The selected server is `RELEASE.2025-10-15T17-29-55Z`, commit
`9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`. This release fixes the session-policy
bypass reported upstream. Its release instructions require building the
container from source. The client is `RELEASE.2025-08-13T08-35-41Z`, commit
`7394ce0dd2a80935aded936b09fa12cbb3cb8096`. Exact source archive checksums and
base image digests are recorded in `../versions.lock.json` and `Dockerfile`.
The local chart is `0.1.0`; it does not inherit an older upstream chart's image.

The Community server repository was archived on April 25, 2026. This is an
optional reproducibility profile with a known upstream maintenance limit, not a
claim of continuing security support. An organization requiring maintained
storage should select an appropriately supported external S3 service. Do not
substitute an obsolete Apache-licensed MinIO release to avoid the AGPLv3 terms.

Preserve upstream licenses and corresponding source when distributing the built
image. The recipe bundles both projects, their vendored dependencies, Go runtime
sources and the Dockerfile in `/usr/share/minio/corresponding-source.tar.gz`, plus
the two upstream license files. Retain and make that archive available to image
recipients, and fulfill the applicable AGPLv3 source-offer requirements for any
modified network-accessible version. Source files or build changes must remain
available with the actual image being run. The source archive is not automatically
served by the S3 API. Other bundled dependencies and the base image retain their
own licenses; this addition is not a complete third-party license audit.

Primary sources: [server release](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z),
[server license](https://github.com/minio/minio/blob/RELEASE.2025-10-15T17-29-55Z/LICENSE),
[client release](https://github.com/minio/mc/releases/tag/RELEASE.2025-08-13T08-35-41Z),
[repository status](https://github.com/minio/minio),
[AGPLv3 terms](https://www.gnu.org/licenses/agpl-3.0.html).

## Build the server/client image

Docker with a BuildKit frontend supporting `ADD --checksum` (Dockerfile 1.6+),
registry access and enough build memory/disk for the Go
dependencies are required. The build context excludes credentials. The recipe
checks both source archive hashes, verifies Go modules, and fixes base images by
digest. It uses the same Python slim base already recorded for the ETL image.
Changing the Go/toolchain, source or base images requires a new reviewed build.

From the repository root, replace the registry/repository below:

```sh
bash minio/build-image.sh registry.example/alias-minio:RELEASE.2025-10-15T17-29-55Z
docker push registry.example/alias-minio:RELEASE.2025-10-15T17-29-55Z
docker image inspect --format '{{index .RepoDigests 0}}' registry.example/alias-minio:RELEASE.2025-10-15T17-29-55Z
```

The helper only builds; it does not publish. Use the resulting
`registry.example/alias-minio@sha256:...` reference as `MINIO_IMAGE`. The same
image supplies the server and bootstrap client, so both are fixed by that digest.
Keep the image in a registry accessible to the cluster; configure an existing
`MINIO_IMAGE_PULL_SECRET` in namespace `minio` if authentication is needed.
No prebuilt image for this profile is published by this repository.

## Interactive configuration and preview

Python 3, Bash, Helm and `../scripts/requirements.txt` are needed for the tooling.
The wizard runs locally, generates distinct random credentials without displaying
them, writes a new file with mode 600, and refuses to overwrite a file:

```sh
python3 minio/configure.py
export ALIAS_ENV_FILE="$PWD/minio/.env"
bash minio/deploy.sh --render
```

Alternatively, copy `minio/.env.example` to `minio/.env`, restrict it with
`chmod 600 minio/.env`, and fill the fields. These are trusted Bash files loaded
by the existing environment loader. `MINIO_IMAGE` must have a real registry
digest. `--render` needs no kubectl or cluster; its output contains only Secret
references, not credential payloads. It does not deploy anything.

Choose exactly one storage source:

- `MINIO_STORAGE_CLASS`: reuse an existing provisioner with a **new dedicated**
  `ReadWriteOnce` PVC named `minio-data`. The default `local-path` is suitable
  only if that class exists; its node-local storage gives no node failover.
- `MINIO_EXISTING_CLAIM`: use a dedicated filesystem PVC already `Bound` in
  namespace `minio`. Clear `MINIO_STORAGE_CLASS`. Prepare ownership for UID/GID
  1000 and verify that this filesystem satisfies the object store's requirements.
  The script never formats disks or copies/migrates existing data.

The PVC is exclusive to the MinIO data layout. Do not point it at notebook, DAG,
database, registry or GlusterFS export directories used by other applications.
Namespaces cannot mount each other's PVCs. Reuse the storage platform and node
capacity, while keeping the backing volume/directory dedicated. This profile does
not add MinIO to the existing GlusterFS/NFS exports: prefer a dedicated filesystem
with the required I/O and durability behavior rather than stacking the object
store on those shared directories. Object consumers share **buckets through S3**,
never direct access to MinIO's data files.

CPU/memory requests and limits are configurable. Defaults reserve 250m CPU and
512Mi memory, with limits of 1 CPU and 1Gi memory; the temporary bootstrap job
reserves 100m CPU/128Mi and is limited to 500m CPU/256Mi. These are starting
values for the single-server profile, not measured workload sizing. Account for
other Helm workloads' requests and shared disk/network capacity when sizing nodes.

## Deployment, accounts and access

For a real deployment, supply kubeconfig and verify that the cluster CNI enforces
NetworkPolicy, the chosen StorageClass exists, and any private image/TLS Secrets
are ready in namespace `minio`:

```sh
bash minio/deploy.sh
kubectl -n minio get deployment,pod,service,pvc,job
kubectl -n minio rollout status deployment/minio
```

The deployment validates configuration before writes, checks existing storage
without changing it, creates the namespace and external runtime Secrets, then
runs Helm with `--atomic`. Existing credential differences stop the run instead
of silently rotating accounts. The chart uses a Recreate strategy and retains
its PVC on uninstall. StorageClass/claim changes are refused for an existing
deployment; resizing and data migration are separate operations.

`MINIO_CLIENTS=mlflow,spark` creates two independent client profiles. For each,
set `MINIO_<PROFILE>_BUCKETS`, `MINIO_<PROFILE>_ACCESS_KEY` and
`MINIO_<PROFILE>_SECRET_KEY`; replace profile hyphens with underscores in variable
names. Keys use 16..128 ASCII letters, digits, underscores or hyphens. The wizard
generates these keys. Profiles have bucket-scoped object read/write/delete and
multipart permissions, without admin or bucket-deletion permissions. Buckets
remain private. To share datasets, explicitly list the same bucket in both
profiles while keeping distinct credentials. Add the consumers' namespaces to
`MINIO_ALLOWED_NAMESPACES`. Root credentials are for administration/bootstrap only.

The S3 API is `http://minio.minio.svc.cluster.local:9000` by default, reachable
only through a ClusterIP service. HTTP assumes a trusted private network. For
TLS, set `MINIO_TLS_SECRET` to an existing Kubernetes TLS Secret with `tls.crt`
and `tls.key`, including the service DNS name in its certificate SAN. The bootstrap
client trusts that certificate without an insecure TLS bypass. Consumers also
need the corresponding CA in their trust configuration. No ingress, public
endpoint or identity provider is installed automatically.

Only explicitly allowed namespaces can reach S3 port 9000 through the supplied
policy; pods in namespace `minio` can also administer the service. Consumer
namespaces do not get console access on 9001. Administrators can use an authorized
`kubectl -n minio port-forward service/minio 9001:9001` session for the console.

## Optional integration with existing services

After deployment, export a private connection file for a selected profile:

```sh
bash minio/connection.sh mlflow minio/mlflow-connection.env
```

The documented `minio/*-connection.env` path is ignored by Git; keep custom
destinations out of version control too. The command refuses to overwrite files.
It exports only the chosen account and
the first configured bucket, never root or other profiles' credentials. For
MLflow it writes the existing `MLFLOW_S3_*` variables. Merge those values into
MLflow's own trusted configuration alongside its database fields, select that
file with `ALIAS_ENV_FILE`, then run `bash mlflow/deploy.sh`. If its runtime Secret
already uses a different S3 account, deployment deliberately refuses replacement;
plan the credential/data migration first. No existing artifacts are copied.

Other profiles export `S3_ENDPOINT_URL`, `S3_BUCKET`, `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`. Adapt these to each consumer's supported configuration:

| Consumer | Optional use | Additional setup |
|---|---|---|
| MLflow | Tracking/model artifacts | Existing `MLFLOW_S3_*` fields; MySQL remains separate |
| Spark / JupyterHub | Shared datasets via S3A | S3A endpoint, path-style access, account and matching Hadoop dependencies in the workload |
| Airflow | Task data and artifacts | An Airflow S3 connection and task/provider configuration; DAG PVC/Git stays separate |
| Trino | Iceberg/Hive object data | An appropriate catalog, metastore/catalog service and native S3 properties; endpoint alone creates no tables |
| Pinot | Segment deep storage | The S3 filesystem plugin and segment storage settings; ZooKeeper and local working volumes remain |
| Private registry | Optional S3 blob backend | Registry chart storage configuration and a dedicated bucket/account; the current PVC backend is not changed |

These integrations are opt-in. The connection export does not edit other Helm
releases or install plugins, metastore services, workloads or application code.

## Verification and retention

Offline checks, including Helm rendering when `ALIAS_HELM` points to a binary:

```sh
ALIAS_HELM=/path/to/helm python3 -m unittest discover -s scripts/tests -p test_minio.py -v
```

After deployment, test upload/download/delete with each scoped account and check
that it cannot read another profile's private bucket. Verify denial from an
unlisted namespace, restart persistence, TLS trust where configured, and an MLflow
artifact round trip if that integration is selected. No live cluster deployment,
image build, S3 round trip or end-to-end duration has been validated locally.

Helm rollback does not undo S3 objects, IAM policies or buckets created by the
bootstrap job. Reruns preserve existing buckets and attach the declared policies;
removing a profile from configuration does not revoke its old account. Handle
revocation, key rotation, backups and data migration explicitly. External Secrets
and retained PVCs survive release removal; do not delete them as routine cleanup.
Keep independent object backups. A single server/PVC has no object-store HA.
