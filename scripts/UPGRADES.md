# Updating or returning to a previous release

The current baseline is `versions.lock.json` together with `versions/*.values.json`,
component values, Python locks and scripts from the same Git commit. Preserve that
complete commit when releasing a version. These files must move together; changing
only a chart version or image tag is not a supported upgrade path.

Local template rendering does not establish that applications, storage and
external databases work together.
Validate the current baseline once in an independent environment before accepting
it as a known working release. Keep that environment's Git commit, chart revisions,
and backup identifiers as the release record.

## Upgrade

1. Record the current Git commit and `helm history RELEASE -n NAMESPACE`.
   Retain the images and charts referenced by both the source and target commits.
2. Back up databases, persistent volumes and the local environment/Secret values
   securely. Confirm restoration is possible. Read the applications' release notes
   for database migrations, CRDs, supported Kubernetes versions and downgrade limits.
3. Change the locks and configuration together on a branch. Try the target release
   against a restored copy of the data first. Check login, a representative operation,
   data read/write and the intended rollback once; repeated broad checks are not required.
4. Run the component's `bash COMPONENT/deploy.sh`. Chart deployments use
   `helm upgrade --install --atomic --timeout 10m --history-max 20`. Set
   `HELM_TIMEOUT` if the deployment needs longer. Helm waits for readiness and returns
   the release resources to the prior revision if the upgrade fails.

Component scripts refuse changes to existing external runtime Secrets during an
application upgrade; unchanged credentials are reused. Planned credential changes
are a separate operation. Airflow's migration/user jobs run without Helm hooks so
atomic readiness waiting can complete; finished jobs expire after 300 seconds.
An immediate repeated upgrade before a migration job expires can fail on immutable
Job fields; do not bypass this by forcing resource replacement.

## Return to a previous version

For a revision confirmed to be compatible with the current database and CRDs:

```sh
helm history RELEASE -n NAMESPACE
helm rollback RELEASE REVISION -n NAMESPACE --wait --timeout 10m
```

Then use the corresponding repository commit for future operations. Helm rollback
uses the historical rendered manifests, including the pinned images. Do not apply
current values on top of the old chart. Do not use revision zero as an implicit
choice; select the specific revision that was recorded as working.

If the target revision cannot read the current database schema, stop writes and
restore the matching database/PV/Secret backup before starting that version.
A Helm rollback does not undo database migrations, restore PVC data, downgrade
CRDs, or restore external Secrets. If the application does not support the target
schema downgrade and no verified backup exists, there is no safe automatic downgrade.

K3s/Kubernetes and Rancher-managed infrastructure upgrades have their own support
matrices and recovery procedures. They are not covered by application Helm rollback;
use the distribution's documented upgrade/etcd snapshot restore procedure. Never
assume that reinstalling an older K3s binary reverses an infrastructure upgrade.
