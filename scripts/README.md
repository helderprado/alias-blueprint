# Local configuration and runtime Secrets

Copy `.env.example` to `.env`, restrict it with `chmod 600 .env`, and fill the
section for the component being deployed. Empty sections for other components
are allowed. Quote shell metacharacters. This is a trusted Bash file, loaded
with `source`; do not use an untrusted file. Files are loaded from the repository
root even when the script is invoked from another directory. `ALIAS_ENV_FILE`
selects another file. Assignments in the file override exported values; without
a file, exported variables alone are sufficient.

Run the relevant script with Bash, for example `bash jupyterhub/deploy.sh`.
Deployment scripts validate all required inputs before contacting Kubernetes.
External databases, users and S3 buckets must already exist. Airflow, MLflow, OpenSearch, OpenMetadata, Trino and Pinot create their namespaces after validation; other component namespaces
must already exist.

| Entry script | Runtime Secrets | Consumer |
|---|---|---|
| `trino/deploy.sh` | `trino-auth`, `trino-runtime`, `trino-tls`, optional `trino-catalogs` | SQL authentication, TLS and source configuration |
| `pinot/deploy.sh` | None in this private profile | Namespace policy plus persistent Pinot/ZooKeeper |
| `jupyterhub/deploy.sh` | `jupyterhub-runtime` | Hub Secret references for encryption and dummy authentication |
| `opensearch/deploy.sh` | `opensearch-security`, `opensearch-tls` | Authenticated persistent search backend |
| `openmetadata/deploy.sh` | `openmetadata-runtime`, `openmetadata-jwt` | Server credential references, OIDC, Fernet and JWT volume |
| `mlflow/deploy.sh` | `mlflow-runtime` | Chart external database and S3 credential references |
| `superset/deploy.sh` | `superset-runtime` | Explicit pod environment references and Redis dependency |
| `airflow/deploy.sh` | `airflow-fernet`, `airflow-webserver`, `airflow-metadata` | Official chart existing-Secret options |
| Registry pull-secret wrappers | `regcred` | Dedicated `registry-puller` ServiceAccount |

Secret payloads are sent to `kubectl` through stdin. Temporary Helm overrides
contain Secret names and non-sensitive configuration, never passwords or tokens;
the files are mode 600 and removed on exit. Application credentials reside in
Kubernetes Secrets: restrict access to those objects. Scripts disable shell
tracing before loading local configuration.

`registry/gen-pass.sh` also consumes `REGISTRY_USER` and `REGISTRY_PASSWORD`, and
writes only a bcrypt file in the ignored `registry/registry-creds/` directory.
`registry/deploy.sh` consumes that file. Registry account permissions must be
assigned by the registry operator; rejecting administrative usernames cannot
prove the account is read-only.

Airflow uses the external database in `AIRFLOW_DATABASE_URL`; the bundled
PostgreSQL is disabled by the generated override. This does not create the
external database or initialize credentials on an existing database server.
Superset uses the external PostgreSQL database in its variables and chart-managed
Redis authentication. The scripts do not provision database infrastructure.
Default Airflow and Superset application-user creation stays disabled; configure
user onboarding separately. JupyterHub retains the original dummy authenticator
with a required password; use a proper identity provider for multi-user security.

No historical cluster is accessed. Test commands use synthetic inputs and mocks;
a successful local check does not establish a successful Kubernetes deployment.

## Version locks

Install `scripts/requirements.txt` in the Python environment used by the Helm
post-renderer. Charts read `versions.lock.json`; `versions/*.values.json` supplies
immutable image references for normal workloads and Helm hooks. An unrecognized
floating image causes rendering to fail. See `VERSIONS.md` for the new baseline
and its validation limits. The default Hub uses the official pinned image; the
existing pod hook uses the built-in asynchronous Kubernetes client.

## Upgrade and downgrade

See `UPGRADES.md` for the release procedure, atomic Helm deployment and the
limits of rollback for databases, CRDs and external Secrets.

For catalog deployment and MLflow metadata ingestion setup, see `../openmetadata/README.md`.

OpenSearch and Airflow are independently deployable services. Their component
`.env.example` files contain only their own variables; select a component's local
`.env` with `ALIAS_ENV_FILE`. OpenMetadata optionally consumes a search endpoint;
set its `OPENMETADATA_SEARCH_*` credentials and truststore explicitly. It does not
provision that service, and pipeline integration with Airflow stays disabled by
default. See each component's README.

Trino and Pinot are independent query services. Their optional connection and
access profiles are documented in `../trino/README.md` and `../pinot/README.md`.
