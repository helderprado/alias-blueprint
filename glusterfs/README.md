# GlusterFS shared storage

This optional storage layer follows the repository's Bash entrypoints,
`ALIAS_ENV_FILE` configuration and committed version locks. GlusterFS runs as
host services, like the K3s installation. NFS-Ganesha exports it to Kubernetes
through static NFSv4.1 PVs and `ReadWriteMany` PVCs. No new container images,
Helm release or Kubernetes storage operator is required.

The Kubernetes GlusterFS volume driver was removed in 1.26, so a `glusterfs:`
PV is not suitable for the repository's K3s 1.34 baseline. NFS volumes remain
supported; Ganesha's `FSAL_GLUSTER` accesses GlusterFS through libgfapi.
See [Kubernetes storage](https://kubernetes.io/docs/concepts/storage/volumes/#nfs)
and [NFS-Ganesha's GlusterFS integration](https://github.com/nfs-ganesha/nfs-ganesha/wiki/GLUSTER).

## Configuration and preview

No hosts, disks or live cluster are included. Before a real deployment, provide
three Ubuntu 22.04 amd64 storage hosts (which may also be K3s nodes), each with
an existing dedicated filesystem mounted at `GLUSTERFS_BRICK_MOUNT`. Replica 3
stores three copies; three equally sized bricks provide roughly one brick's
usable capacity, before filesystem overhead. More nodes must form groups of
three. A single node with `GLUSTERFS_REPLICA_COUNT=1` is supported for development
and has no redundancy. The scripts do not create machines, format disks, edit
fstab, or change firewalls.

Copy the template and replace the example hostnames, gateway and client networks:

```sh
cp glusterfs/.env.example glusterfs/.env
chmod 600 glusterfs/.env
export ALIAS_ENV_FILE="$PWD/glusterfs/.env"
```

The same file must be available on the hosts where provisioning runs. All paths
below assume the repository root; `ALIAS_ENV_FILE` must be absolute. Ordinary
entrypoints also work from another directory. Python 3 and Bash are required.

Preview the volume creation commands, Ganesha configuration and Kubernetes
resources without root access, packages, hosts, Helm, kubectl or cluster access:

```sh
bash glusterfs/create-volume.sh --render
bash glusterfs/gateway.sh --render
bash glusterfs/deploy.sh --render
```

`GLUSTERFS_CLIENT_CIDRS` lists the trusted **node** IPs/subnets from which NFS
mount requests originate, not Kubernetes Service addresses. Empty values,
wildcards and default-route CIDRs are rejected. NFS access is denied outside
this list. AUTH_SYS trusts the permitted hosts' numeric user identities;
root access within these networks allows workloads to initialize ownership.
Use a private trusted storage network: this profile does not add NFS encryption
or Kerberos. Restrict TCP 2049 to those clients and GlusterFS management/brick
ports to storage peers and the gateway. Apply firewall rules for the deployed
GlusterFS version using its [network guide](https://docs.gluster.org/en/latest/Administrator-Guide/Network-Configurations/).

## Host provisioning

On **each storage host**, after mounting its dedicated filesystem:

```sh
sudo --preserve-env=ALIAS_ENV_FILE bash glusterfs/install-node.sh server
```

On the **first** host listed in `GLUSTERFS_NODES`, create/start the volume:

```sh
sudo --preserve-env=ALIAS_ENV_FILE bash glusterfs/create-volume.sh
```

The script probes the other peers and creates one brick per host, underneath
the dedicated mount. It never uses `force`. It reuses a matching volume, refuses
topology changes, and stops on failed inventory queries. If peer connection is
still settling, wait for `gluster peer status` to show connected peers and rerun.

On the host selected as the **NFS gateway** (it may be a storage host):

```sh
sudo --preserve-env=ALIAS_ENV_FILE bash glusterfs/install-node.sh gateway
sudo --preserve-env=ALIAS_ENV_FILE bash glusterfs/gateway.sh
```

The gateway temporarily mounts the native GlusterFS volume to create the selected
`notebooks`, `dags` and optional `registry` directories. Only new directories get
the configured numeric owners and mode 2770; existing data is never recursively
chowned or chmodded. It writes a managed `/etc/ganesha/ganesha.conf` and enables
`nfs-ganesha`. If a packaged sample or an unrelated configuration already exists,
back it up and move it aside deliberately before running this script. Changes
to a managed configuration require stopping Ganesha first; identical reruns reuse
it. The first storage host must be reachable when the gateway initializes.

Install the NFS mount helper on **every K3s node** that can run consumers:

```sh
sudo --preserve-env=ALIAS_ENV_FILE bash glusterfs/install-node.sh client
```

The scripts install exact package revisions from `versions.lock.json` and reject
downgrades. Enable the Ubuntu `jammy-updates`/`universe` repositories beforehand.
If a locked revision is unavailable, provisioning fails instead of selecting a
different release. Other OS dependencies remain managed by the host's APT
repositories; preserve the host image and a repository snapshot for full host
reproducibility. The package lock does not pin the kernel or complete OS.

## Kubernetes consumers

After the export is ready, run with cluster credentials:

```sh
bash glusterfs/deploy.sh
kubectl get pv
kubectl -n jupyterhub get pvc nfs-share-pvc
kubectl -n airflow get pvc airflow-share-dag-pvc
kubectl -n spark-operator get pvc airflow-share-dag-pvc
```

| Profile | Namespace / claim | Export directory | PV capacity |
|---|---|---|---|
| `jupyterhub` | `jupyterhub/nfs-share-pvc` | `notebooks` | 30Gi |
| `airflow` | `airflow/airflow-share-dag-pvc` | `dags` | 5Gi |
| `spark` (opt-in; current jobs) | `spark/airflow-share-dag-pvc` | `dags` | 5Gi |
| `spark-operator` (legacy) | `spark-operator/airflow-share-dag-pvc` | `dags` | 5Gi |
| `registry` (opt-in) | `docker-registry/docker-registry-pv-claim` | `registry` | 20Gi |

JupyterHub's existing values already name this claim. Prepare user subdirectories
under `notebooks` for the configured `{username}` subPath before starting their
servers. For Airflow, set `AIRFLOW_DAGS_PVC=airflow-share-dag-pvc` in **Airflow's**
environment and redeploy it; `ALIAS_ENV_FILE` must select the consumer's own file
for that operation. Airflow and Spark jobs use separate namespaced claims
pointing at the same `dags` directory; task definitions still need to mount their
claim. Align the DAG UID/GID with those workloads. Append `registry` to
`GLUSTERFS_PROFILES` to include the registry's existing claim name; its directory
defaults to UID/GID 1000:1000, matching the pinned registry chart's security context.

For the current [Spark job profile](../spark/README.md), select `spark` instead
of `spark-operator` in `GLUSTERFS_PROFILES` and rerun this deploy after reviewing
the manifests. The `spark` claim points at the same DAG export in the job
namespace; set `SPARK_DAGS_PVC=airflow-share-dag-pvc` in Spark's own environment
for a read-only mount. Old `spark-operator` claims are preserved and not migrated.

PV capacity fields are binding metadata, not enforced directory quotas; all
directories share the backing GlusterFS volume's space. This does not provide an
S3 endpoint for MLflow or change the default StorageClass, chart-managed database
storage, OpenSearch or Pinot volumes. The original component local PV examples
are alternatives: do not apply them to the same claims.

The deploy validates every selected PV/PVC before any writes. An existing claim
backed by local storage, a changed NFS endpoint, or an unmanaged resource causes
it to stop. Existing data migration requires separate backup/copy/restore; this
script never deletes/replaces PVCs. All PVs use explicit bindings, an empty
StorageClass and `Retain`, so the default local-path provisioner cannot select
them and deleting a claim does not deliberately erase data. Retained PVs need
manual review before reuse after claim deletion.

## Verification and maintenance

Offline checks:

```sh
python3 -m unittest discover -s scripts/tests -p test_glusterfs.py -v
```

After host provisioning, inspect `gluster peer status`, `gluster volume info
alias-data`, `gluster volume status alias-data` and `gluster volume heal alias-data
info` (substitute your configured volume). Verify the NFS mount from a trusted
K3s node and perform a write/read test as the consumer's UID. Finally check that
a Pod scheduled on another node reads the same test data through its PVC.
These host, failover and workload checks have not been run locally.

This profile configures a **single NFS gateway**. GlusterFS replication does not
provide gateway failover; gateway loss interrupts client access. A redundant
NFS-Ganesha/VIP deployment requires a separate HA design. Replication is not a
backup. Keep independent data backups and the matching package/configuration
revision. There is no destructive `undeploy.sh`: stop consumers and plan data
retention before removing PVs, exports or bricks. See `../scripts/UPGRADES.md`.
