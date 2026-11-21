# Apache Spark jobs on Kubernetes

The independent Spark Operator release watches **namespace `spark`**. Its
controller runs in `spark-operator`; drivers, executors, credentials and optional
shared-file claims run in `spark`. This provides batch compute, not a second
always-running Spark master/worker cluster. Spark, the Spark Operator and the image
recipe retain their Apache-2.0 licensing; JDBC and other dependencies retain their
own licenses. MinIO remains a separate optional AGPLv3 service.

## Configuration and offline preview

Use Bash, Python 3 with `scripts/requirements.txt`, Helm at the project's pinned
version and kubectl for the target K3s cluster. From the repository root:

```sh
cp spark/.env.example spark/.env
chmod 600 spark/.env
export ALIAS_ENV_FILE="$PWD/spark/.env"
bash spark/setup.sh --render
bash spark/submit.sh --render
```

These two previews need no cluster, credentials, Helm or network for the default
compute-only profile. Optional integrations validate their own selected inputs;
previews contain references to credentials, never Secret payloads. Environment
files are trusted Bash files; file assignments override exported variables.
Scripts resolve repository paths independently of the current directory.

The default job uses the committed immutable Spark `3.5.0` Python image. The
Spark Operator chart remains `1.3.2`, with image `v1beta2-1.5.0-3.5.0` fixed by digest.
The admission webhook is enabled because the example uses ConfigMap mounts and
optional Secret references. The Kubernetes API server must be able to reach the
webhook Service. This baseline has not been validated against a live K3s cluster.

Preview the Spark Operator using the locked chart downloaded by Helm:

```sh
bash spark-operator/deploy.sh --render
```

For fully offline rendering, set `SPARK_OPERATOR_CHART` in the selected environment
to an absolute path to the cached `spark-operator-1.3.2.tgz` archive. Both deployment
and preview verify its SHA-256 against `versions.lock.json`. The Spark Operator preview
renders only the Helm release; `spark/setup.sh --render` shows workload resources.

## Bootstrap and permissions

After reviewing the previews, install the Spark Operator and prepare the workload
namespace in one command:

```sh
bash spark-operator/deploy.sh
bash spark/submit.sh
kubectl -n spark get sparkapplications,pods
kubectl -n spark get sparkapplication alias-spark-smoke -o yaml
```

The Spark Operator installer validates configuration and the chart before setup, then
uses `helm upgrade --install --atomic --timeout 10m --history-max 20`. The setup
step is independently rerunnable with `bash spark/setup.sh`. Its namespace,
ServiceAccount, Role/RoleBinding, quotas and smoke-code ConfigMap use declarative
apply. It creates only the runtime Secrets needed by explicitly enabled S3 or
database access and refuses changes to existing credential data. These resources
are external to Helm rollback; credential rotation and data migration are separate
operations. `spark-operator/add-roles.sh` is a compatibility wrapper for this setup.

The driver account has explicit Pod/Service/ConfigMap verbs and read-only PVC
inventory within `spark`. It receives no Secret-read grant or ClusterRoleBinding.
The controller retains the pinned chart's separate cluster permissions for CRD,
webhook and controller operations; driver credentials are not controller credentials.

The previous `spark-operator/add-roles.sh` created a global `spark-role` binding
to `edit` for `spark-operator:spark`. Setup now detects that legacy grant and
stops before writes. Inspect it with `kubectl get clusterrolebinding spark-role
-o yaml`, plan migration of any old jobs, and have the cluster administrator
revoke the obsolete grant before retrying. The new scripts do not silently
delete permissions or migrate running workloads. The retained
`spark-operator/database-secrets.yaml` path is an empty Kubernetes List directing
administrators to the runtime workflow; it no longer creates unusable empty credentials.

## Resource budget

The defaults bound this smoke check's driver and one executor:

| Workload | CPU request / limit | JVM memory / additional overhead |
|---|---|---|
| Driver | 500m / 1 core | 512m / 384m |
| Each executor (one by default) | 500m / 1 core | 1g / 384m |
| Spark Operator, separate namespace | 100m / 500m | 256Mi request / 512Mi limit |

`SPARK_DRIVER_*`, `SPARK_EXECUTOR_*` and `SPARK_EXECUTORS` configure the job.
Dynamic allocation is disabled. Kubernetes Pod memory includes Spark memory plus
overhead; Python/native workloads may require more overhead than these defaults.

The **aggregate** `spark` ResourceQuota limits requests and limits to 4 CPUs and
8Gi memory and caps Pods at 12. Adjust `SPARK_QUOTA_CPU`, `SPARK_QUOTA_MEMORY`
and `SPARK_QUOTA_PODS` to the capacity reserved for Spark. The job generator
rejects a single job larger than the configured CPU/memory/Pod budget. Concurrent
jobs can still wait or be rejected when the remaining namespace budget is smaller.
An ephemeral-storage LimitRange supplies 512Mi request/2Gi limit per container;
the namespace caps aggregate ephemeral requests at 8Gi and limits at 16Gi.

These controls bound CPU/memory allocation and scratch-space consumption. They
do not reserve physical disk IOPS, network bandwidth or capacity in shared NFS
directories, and do not eliminate contention with other Helm workloads. Size all
node reservations together. Use separate node pools/disks when workload isolation
requires it; no dedicated nodes or network policy are silently installed here.

## Optional MinIO or external S3

First build/publish the S3/JDBC image and retain its actual registry digest:

```sh
docker build -t registry.example/alias-spark:3.5.0 docker-images/pyspark-aws-psql
docker push registry.example/alias-spark:3.5.0
docker image inspect --format '{{index .RepoDigests 0}}' registry.example/alias-spark:3.5.0
```

The recipe adds checksum-verified Hadoop AWS, AWS SDK and PostgreSQL JDBC JARs
from `jars.lock.json`. The base must already provide Hadoop client API/runtime
`3.3.4`; a second `hadoop-common` JAR is not added. Sources are Maven Central.
The downloaded bytes were checked against their published SHA-1 values and their
SHA-256 values are committed for build-time enforcement. This fixes artifact
identity, not a new dependency-version or vulnerability audit. The image build
and application compatibility still need validation in the target environment.

Set `SPARK_IMAGE=registry.example/alias-spark@sha256:...` to the real resulting
digest. For a private registry, create its pull Secret in namespace `spark` and
set `SPARK_IMAGE_PULL_SECRET`. The existing `spark/docker-secret.sh` wrapper can
prepare `regcred` using the registry configuration; set that name explicitly.

For MinIO, create a **spark** client profile with a dedicated account and selected
buckets, and include **spark** in `MINIO_ALLOWED_NAMESPACES`. After its deployment:

```sh
bash minio/connection.sh spark minio/spark-connection.env
```

Merge that connection file's `S3_ENDPOINT_URL`, `S3_BUCKET`, `AWS_ACCESS_KEY_ID`
and `AWS_SECRET_ACCESS_KEY` into Spark's private environment file, or supply the
equivalent `SPARK_S3_*` fields. Set `SPARK_S3_ENABLED=true`. For external S3, use
the same explicit endpoint/bucket/account fields without installing MinIO. Root
MinIO credentials are not used. HTTPS endpoints with private CAs need that CA
installed in the built image's Java truststore; do not disable TLS verification.

Rerun setup and submit using a new application name. Both driver and executor
receive standard AWS environment variables through `spark-runtime` Secret refs.
S3A uses its environment credential provider, configured endpoint and path-style
access. No access/secret key is placed in Spark properties, CRDs or command lines.
The smoke check writes, reads and deletes only its randomly named synthetic
Parquet dataset under `s3a://BUCKET/alias-smoke/`. Failed runs may leave that
test prefix for explicit cleanup. No existing datasets are overwritten.

For JDBC tasks, independently enable `SPARK_DB_ENABLED=true` and set
`SPARK_DB_URL`, `SPARK_DB_USER`, `SPARK_DB_PASSWORD`. The credentials are injected
as `DATABASE_URL`, `DATABASE_USER`, `DATABASE_PASSWORD` into both Pod types.
Applications must explicitly configure their JDBC reader/writer from these
variables; the included smoke check does not query or modify a database.

## Optional GlusterFS/shared files

The job does not require a PVC. If sharing Airflow-delivered files, provision a
claim in the **job namespace** first. The GlusterFS profile supports:

```sh
# In glusterfs/.env choose GLUSTERFS_PROFILES=jupyterhub,airflow,spark
# Then select that file and run glusterfs/deploy.sh after host/export provisioning.
```

The opt-in `spark` profile creates `spark/airflow-share-dag-pvc` for the existing
`dags` export. The older `spark-operator` profile remains supported for existing
claims; its resources are neither moved nor deleted. Select Spark's own environment
again and set `SPARK_DAGS_PVC=airflow-share-dag-pvc`. Submission requires that PVC
to be Bound in `spark` and mounts it **read-only** at `/opt/spark/shared` on driver
and executors. Numeric group 0 must have read/traverse access to the delivered
files, consistent with the supplied GlusterFS DAG directory ownership. The Spark
profile runs as UID 185/GID 0, with privilege escalation disabled.

MinIO is accessed through S3; its data PVC is never mounted by Spark. Job scratch
space is ephemeral. Notebook homes and DAG volumes are not Spark shuffle disks.
The included test code is a ConfigMap and needs none of these optional files.

## Execution checks and limitations

Inspect application status and the driver Pod logs until the application reports
`COMPLETED` and `ALIAS Spark distributed smoke check passed.`. Inspect executor
Pods to confirm distributed execution. Failed/pending Pods need resource, image,
webhook and storage checks; manifest rendering alone proves no running job.

Submission uses Kubernetes `create`, refuses a name that already exists and never
automatically restarts or patches a running job. Change `SPARK_APPLICATION_NAME`
in the environment file for a distinct run. Completed applications have a 600-second
cleanup TTL; collect status/logs before then. The smoke job is a reproducibility
check, not an ETL pipeline, model-training workload or performance benchmark.

Offline checks:

```sh
python3 -m unittest discover -s scripts/tests -p test_spark.py -v
```

Set `ALIAS_HELM=/path/to/helm` and
`ALIAS_SPARK_OPERATOR_CHART=/path/to/spark-operator-1.3.2.tgz` to include rendering
of the exact chart, hook images and CRD fields. No cluster deployment, full image
build, database operation, S3/NFS round trip or execution duration has been measured
locally. See `../scripts/UPGRADES.md` before changing CRDs, images or chart versions.

Primary references: [Spark on Kubernetes](https://spark.apache.org/docs/3.5.0/running-on-kubernetes.html),
[Hadoop 3.3.4 S3A](https://hadoop.apache.org/docs/r3.3.4/hadoop-aws/tools/hadoop-aws/index.html),
[pinned Spark Operator chart](https://github.com/kubeflow/spark-operator/releases/tag/spark-operator-chart-1.3.2).
