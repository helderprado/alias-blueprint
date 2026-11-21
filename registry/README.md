# Runtime credentials

Export `REGISTRY_HOST`, `REGISTRY_USER`, and `REGISTRY_PASSWORD` from your local
ignored environment file or secret manager before running a pull-secret wrapper.
The entry scripts load the repository-root `.env` automatically; see `../scripts/README.md`. Missing values fail before any
Kubernetes request. Do not enable shell tracing when supplying credentials.

Use a dedicated registry account with repository pull permission only. The script
rejects `admin` and `root`; the registry administrator must enforce the actual account
permissions. No registry account is created or changed by these scripts.

Run the appropriate wrapper with Bash:

- `airflow/docker-secrets.sh`
- `jupyterhub/docker-secret.sh`
- `spark/docker-secret.sh`
- `spark-operator/docker-secret.sh`

These four wrappers call `registry/create-pull-secret.sh`. The helper submits
`regcred` and a dedicated `registry-puller` Kubernetes ServiceAccount in the
wrapper's namespace, which must already exist. Override the account name with
`REGISTRY_SERVICE_ACCOUNT`. It references `regcred`, does not automatically mount
a Kubernetes API token, and receives no RoleBinding or ClusterRoleBinding.
Credentials travel through stdin; no credential files or command-line password
arguments are generated.

A workload must explicitly select this account with
`spec.serviceAccountName: registry-puller` to use it. Workloads such as Spark that
need Kubernetes API access require their own reviewed RBAC and token settings;
these scripts do not replace existing workload accounts or grant permissions.

## Component authentication

Component deploy scripts now create their runtime Secrets from the variables in
`.env.example` before invoking Helm. See `../scripts/README.md` for required
inputs, generated Secret names, and consumer references.

Removal from the working tree does not purge prior Git commits. No cluster
operation has been performed during this cleanup.
