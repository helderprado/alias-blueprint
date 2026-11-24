# Article installer and local Kubernetes smoke checks

From the repository root:

```sh
python3 scripts/local-smoke.py --plan
python3 scripts/local-smoke.py --check
sudo bash install-k3s.sh --smoke --components local
```

`install-k3s.sh` is the only installation entrypoint. Without arguments it installs
the article's K3s system service. `--smoke` delegates to the test runner, which
executes that same real shell script without `--smoke`, verifies its installation,
then installs and tests the components inside Kubernetes. There is no separate
preinstalled K3s image or alternative cluster installer.

When Docker is available, run the same installer in a disposable Ubuntu 22.04
host with systemd, without installing a system service in your WSL distribution:

```sh
bash install-k3s.sh --smoke --test-host docker --components storage,databases
# All components supported by a single local host:
bash install-k3s.sh --smoke --test-host docker --components local
```

The host image pins its Ubuntu digest. The native article script runs inside it
and starts the real K3s systemd service; component Pods run in that Kubernetes
cluster. Docker only provides the test host. Anonymous volumes for
`/var/lib/rancher/k3s` and `/var/lib/kubelet` prevent nested overlayfs failures
while preserving the article's default snapshotter. This validates a container
host environment, not a separate VM, bare-metal machine, or multi-host cluster.
No repository credential directories are copied into the host. Only current
Git sources and public chart/client caches are transferred.

Use a clean Linux/WSL2 amd64 test host or VM with systemd and administrative
access. An existing K3s installation is refused. Python 3 with venv support, curl,
Git, OpenSSL and Java `keytool` must be available. The article host baseline is
Ubuntu 22.04; running on another distribution does not validate that baseline.
WSL2 needs systemd enabled. `sudo python3 scripts/local-smoke.py --check` checks
the prerequisites without installing services.

The runner uses the committed K3s configuration, adding only a private-registry
file and a node ownership label. It preserves normal K3s defaults, including
Traefik and ServiceLB. The corrected article option is
`service-node-port-range: 1000-32767`. Native validation checks the installed
binary version, active systemd service, Ready node, CoreDNS, and API acceptance
of a Service with NodePort 10000. Only then is `install-k3s` recorded as PASS.
The report includes hashes of the entrypoint and article configuration.

K3s supplies containerd. Custom image builds use the pinned BuildKit image in a
privileged Kubernetes Pod; registry authentication is mounted from a Secret.
Images are pushed to the test registry and consumed by K3s using verified
manifest digests. No host Docker daemon or host image builder is required.
Helm is a deployment client; it and Python dependencies are prepared under
ignored `.local-smoke/` when the locked versions are unavailable.
`ALIAS_HELM=/absolute/path/to/helm` can select the locked Helm client.
Downloads of K3s, charts, images, Python packages, Go modules and Maven artifacts
require outbound network access. No existing component `.env`, credentials,
volumes or kubeconfig are reused. The component source snapshot includes
versioned files and their current edits; generated credentials are test-only.

The complete sequence has passed on a machine with 6 CPUs and approximately
12.7 GiB available at preflight, with sufficient disk space for images, Go build
caches and PVCs. This measures sequential smoke checks with services unloaded
after their last consumer, rather than every service running simultaneously.
The runner refuses to start below 8 GiB available. Services are unloaded after
their final consumer to release memory; the local Trino profile uses smaller
heaps and resource requests. PVC data stays on the native K3s host until the test
namespaces/PVCs are deleted. Initial source builds of MinIO and Spark can take much
longer than subsequent runs.

## Measured local run

Host run `20261123T193921Z-1c7f74` passed the automated `test_live_k3s.py` test
with its default `local` component selection. It installed a new K3s cluster
through the article entrypoint (`cluster.resumed: false`), passed all 17
functional stages, requested deletion of the owned test namespaces and removed
the Docker host and anonymous volumes. All 21 report entries are PASS.

The native sequence took **1721.96 seconds (28 min 42 s)**; the enclosing
automated test took **1740.121 seconds (29 min)**, including host preparation,
artifact collection and disposal. The Ubuntu/systemd host image and public Helm
charts were cached. Kubernetes storage and containerd state were fresh, and the
MinIO and Spark images were rebuilt with BuildKit. These timings describe this
single-host synthetic run, not a cold OS installation or production replication.

The private local evidence is under:

```text
.local-smoke/hosts/20261123T193921Z-1c7f74/host-report.json
.local-smoke/hosts/20261123T193921Z-1c7f74/artifacts/20261123T193926Z-d206f6/report.json
```

The offline suite also passed 60 tests; two optional checks were skipped in that
invocation, including the live test executed separately above. A separate real
K3s check verified ownership-label preservation after component-style Namespace
apply, guarded namespace deletion and host removal before the complete rerun.

## Coverage

| Stage | Functional assertion |
|---|---|
| install-k3s | Run the article shell installer; check systemd, locked version, Ready node, DNS and NodePort 10000 |
| Storage | One Pod writes a PVC; a different Pod reads the same bytes |
| Databases | PostgreSQL and MySQL insert/select/drop temporary tables; create separate application users/databases; additional Pods query each database through Service DNS |
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
| Rancher | Verified HTTPS, bootstrap authentication and local cluster API |
| GlusterFS | Report BLOCKED: the replicated profile needs three separately prepared storage hosts |

OpenMetadata uses basic/JWT authentication exclusively in the local override.
External OIDC, browser login, the official MLflow ingestion connector and its
Airflow ingestion plugin are outside this test. The metadata import is a direct
API workflow. JupyterHub uses the repository's dummy authenticator; notebook code
is executed in the spawned Pod, rather than through the browser/kernel protocol.
Superset checks the query and stored dashboard objects, not browser rendering.
pgAdmin's database check uses its Python environment and server definition, not
the query-tool UI. Rancher uses its namespace's HTTPS Service with the configured
hostname/SNI and the cluster CA; external routing is outside this check. Trino and
OpenSearch retain certificate verification. Local PVC checks do not validate
GlusterFS replication, NFS-Ganesha, failover, throughput or production security.

The native service listens according to the article K3s configuration; its normal
Traefik/ServiceLB components are preserved. The test registry uses NodePort 30500;
other test application Services use ClusterIP. This is a real host installation,
so use a dedicated test machine or VM. OpenSearch may temporarily raise the host
kernel's `vm.max_map_count`; the
previous value is restored on normal exit or Ctrl+C, including with `--keep`.
An uncatchable termination such as SIGKILL can prevent that restoration.

## Select components and inspect failures

Dependencies are included automatically, in order:

```sh
sudo bash install-k3s.sh --smoke --components spark
sudo bash install-k3s.sh --smoke --components superset
sudo bash install-k3s.sh --smoke --components airflow,jupyterhub,openmetadata,superset,pgadmin,homepage,rancher
```

`--components local` is a shorter equivalent of the last command, selecting all
locally testable components, excluding the known
multi-host GlusterFS limitation. `--components all` is the default and explicitly
includes that limitation as a BLOCKED result, so it cannot return complete success
on a single-node machine. Each installation run requires a fresh host/VM; an
already installed K3s is never silently replaced.

For debugging a retained, owned Docker host, retry component checks without
reinstalling the verified K3s service:

```sh
bash install-k3s.sh --smoke --test-host docker --resume-host HOST_RUN_ID \
  --components openmetadata,superset,rancher --keep
```

Resuming verifies both ownership labels and unchanged installer/configuration
hashes. It preserves prior reports under `attempts/`, reuses test credentials and
built images, refreshes versioned component sources, and reruns selected checks.
The report marks `cluster.resumed: true`; the native installer is not reexecuted.
Do not report resumed timings as a fresh replication measurement. Native hosts
can use `--resume-run RUN_ID` instead; arbitrary existing clusters remain refused.

The smoke database profile uses pinned MySQL 8.4.7 on a dedicated `mysql84-data` PVC.
MLflow 3.16 model-list/get queries use SQL window functions, which failed against
the legacy MySQL 5.7 example during live verification. The smoke runner explicitly
checks `ROW_NUMBER()`, application-owned triggers and model retrieval/listing.
Its isolated MySQL enables `log_bin_trust_function_creators` so MLflow migrations
can create their triggers without granting the application SUPER privileges.
It does not mount or upgrade the old `mysql` PVC. The database stage reads the
Deployment from the updated `databases/mlflow-db/deploy.yaml`, substituting only
test identity, Secret references and a dynamic PVC; image, server arguments,
probes and update strategy are exercised from the committed definition. It also
asserts the running server reports version 8.4.7. The
[database example](../databases/mlflow-db/README.md) now uses a separate 8.4
static PV/PVC and an external Secret with the official `MYSQL_*` variables.
Existing 5.7 data needs a separately planned migration before cutover.

After updating that database example, targeted run `20261123T204133Z-bd22d5`
selected `openmetadata` and its dependencies. All 11 entries passed, including
the fresh article installation, running MySQL 8.4.7, MLflow, OpenMetadata and
cleanup. The enclosing automated test took 695.498 seconds and confirmed Docker
host disposal. See the database example's README for the repeat command and
local evidence paths. This targeted rerun does not replace the earlier complete
single-host run above.

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
  kubeconfig           private copy of this native K3s cluster's credentials
  native.json          native client path and owned test namespaces
  k3s-config.yaml      article configuration plus registry/node-label additions
  registries.yaml      test registry settings referenced by the native service
```

With `--test-host docker`, the outer report, host package inventory and copied
inner run artifacts are under `.local-smoke/hosts/HOST_RUN_ID/`. The outer report
records the host image ID, inner report paths, exit status and disposal result.
Without `--keep`, the Docker host and its anonymous volumes are removed after
artifact collection, including after a failed test. With `--keep`, the report
records the retained container name for inspection with `docker exec`.

Reports, inputs and logs are private files. Generated credentials are removed from
command logs; kubeconfig/Secret reads suppress their output. Administrative runs
produce root-owned private files. The directory still
contains credentials and keys needed by the test installation, and is ignored by
Git. Do not publish the entire run directory. Keep the run directory while this
native service is installed: its config references files there. Chart archives
and containerd images remain cached; the BuildKit Pod's build cache is ephemeral.

Results distinguish `PASS`, `FAIL`, `BLOCKED` and `NOT_RUN`. A dependency failure
blocks its consumers; independent stages continue. Preflight failure records
NOT_RUN for every component and exits nonzero without provisioning a cluster.
The exit code is zero only when every selected functional stage and cleanup
succeeds, with namespace deletion requested where applicable. `--check` only
checks prerequisites and deliberately records functional
checks as NOT_RUN; it is not a functional success report.

The native K3s service is always retained. By default, after diagnostics the
runner requests deletion of its labelled test namespaces/PVCs; namespace deletion
is asynchronous, and controller finalizers can delay completion. Retain test
namespaces for inspection with:

```sh
sudo bash install-k3s.sh --smoke --components spark --keep
sudo k3s kubectl get pods -A
sudo python3 scripts/local-smoke.py --cleanup RUN_ID
```

Finished services are still unloaded with `--keep`; retained PVCs and logs support
inspection without requiring all services to stay in RAM. Cleanup checks the
cluster marker and each namespace's ownership label before requesting deletion.
Ownership labels are applied separately from the Namespace manifest so component
scripts using client-side `kubectl apply` cannot prune them through last-applied
configuration. A missing or mismatched label still stops deletion.
The control namespace, cluster-wide CRDs and resources created by third-party
controllers may remain. Neither automatic nor explicit test cleanup calls
`k3s-uninstall.sh`, removes the system service or deletes unrelated namespaces.
Discard the test VM when finished, or use K3s's own uninstall procedure separately.

## Validate the runner without services

```sh
python3 -m unittest discover -s scripts/tests -p test_install_k3s.py -v
python3 -m unittest discover -s scripts/tests -p 'test_local_smoke*.py' -v
```

Run the automated real installation/communication test with a working Docker
daemon (this is opt-in so ordinary unit tests do not provision infrastructure):

```sh
ALIAS_RUN_K3S_E2E=1 python3 -m unittest discover -s scripts/tests -p test_live_k3s.py -v
```

This installs K3s through the article script and tests all single-host components
(`local`), including operations through Services, verifies every result in the
reports, and asserts disposal of the Docker host. Set
`ALIAS_E2E_COMPONENTS=storage,databases` for a smaller installation test, or select
another component group. `ALIAS_E2E_TIMEOUT` overrides the outer deadline of
7200 seconds. Component dependencies are always included automatically.

Optional offline rendering checks the actual local overrides against checksum-
verified official chart archives (the directory uses `NAME-VERSION.tgz` filenames):

```sh
ALIAS_HELM=/path/to/helm \
ALIAS_SMOKE_CHARTS_DIR=/path/to/verified/charts \
python3 -m unittest discover -s scripts/tests -p test_local_smoke_charts.py -v
```

The installer tests execute the real shell entrypoint, replacing only curl and
the upstream installer's response with controlled fixtures. They verify version
and argument forwarding, invalid inputs, partial/empty downloads, upstream errors,
temporary-file cleanup and smoke delegation. Runner tests verify that native
bootstrap invokes this same entrypoint and preserves the article's options.
These local checks validate orchestration/failure behavior and rendered manifests;
they never establish a running service or successful cross-service operation.

Implementation references: [K3s installation/configuration](https://docs.k3s.io/installation/configuration),
[native server options](https://docs.k3s.io/cli/server),
[BuildKit in Kubernetes](https://github.com/moby/buildkit/blob/v0.20.2/examples/kubernetes/pod.privileged.yaml),
[Pinot's small-file upload API](https://docs.pinot.apache.org/build-with-pinot/ingestion/batch-ingestion/batch-ingestion),
[JupyterHub API](https://jupyterhub.readthedocs.io/en/4.x/reference/rest-api.html).
