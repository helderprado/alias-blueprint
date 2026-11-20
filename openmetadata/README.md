# OpenMetadata catalog

This adds the catalog/governance layer to the independent deployment baseline.
It is not a statement that OpenMetadata was measured in the study environment.
The official server chart and image are pinned in `versions.lock.json` and
`versions/openmetadata.values.json`. The namespace and Service are `openmetadata`.

## Prerequisites and deployment

Use the existing `.env` mechanism; fill every required `OPENMETADATA_*` variable
in `.env.example`. You need:

- An existing dedicated PostgreSQL database/user with permissions for the server's
  startup migrations. The default connection uses TLS; set DB_PARAMS for your
  installation deliberately. This script does not provision database infrastructure.
- Deploy `../opensearch/` first for the bundled search backend. The default `.env`
  endpoint is `opensearch.opensearch.svc.cluster.local`; the generated Java
  truststore is mounted into the catalog. The dedicated catalog account is seeded
  from `OPENMETADATA_SEARCH_USER` and `OPENMETADATA_SEARCH_PASSWORD`.
  Alternatively, supply an external supported OpenSearch endpoint. For a public
  CA, leave `OPENMETADATA_SEARCH_TRUSTSTORE_FILE` empty; for a private CA, supply a
  truststore and its password. Do not disable certificate validation.
- An OIDC provider/client, registered redirect URI `PUBLIC_URL/callback`, JWKS and
  discovery URLs. `ADMIN_PRINCIPAL` is your IdP user's principal before the domain.
  There is no seeded local administrative password and self-signup is disabled.
- `openssl`, Python with `scripts/requirements.txt`, kubectl, Helm and cluster access.
  Use a trusted HTTPS route for real use; public URL/routing/TLS are supplied by the
  adopter. The chart Service is ClusterIP and no public ingress is created here.

From any directory:

```sh
bash /path/to/alias-blueprint/openmetadata/gen-keys.sh
bash /path/to/alias-blueprint/openmetadata/deploy.sh
```

The first command creates a JWT key pair only under ignored `runtime-creds/` and
preserves an existing pair. Back it up securely together with the Fernet key.
The deployment validates configuration and key pairing before any cluster write,
creates the namespace, creates missing runtime Secrets, then runs the atomic Helm
upgrade/install. The downloaded chart is verified against its official SHA-256;
the hardcoded upstream Helm-test busybox image is patched to the existing locked
digest before installation. No other upstream template is changed. Existing Secret changes are refused, as for the other components.
Keys are supplied as Kubernetes Secret volumes; credentials never enter Helm values.

For a local access tunnel:

```sh
kubectl -n openmetadata port-forward service/openmetadata 8585:8585
```

The browser URL must match the URL and callback registered with your IdP. A tunnel
alone does not configure OIDC routing or TLS.

## MLflow connection

Deploy the existing `mlflow/` component first. Within the cluster its default API
is `http://mlflow.mlflow.svc.cluster.local:5000`. In OpenMetadata, add an ML Models
service using the MLflow connector, and use that API for both tracking and model
registry URI (or your actual authenticated endpoint).

Deploying the catalog does not ingest models by itself. Configure and run an
OpenMetadata MLflow ingestion workflow using the same OpenMetadata release and
an ingestion bot token. No ingestion token is shipped or committed. Automatic
pipeline deployment is disabled: this chart does not silently install another
Airflow or assume the existing Airflow has the OpenMetadata ingestion plugin.

## Maintenance

Use `../scripts/UPGRADES.md`. Startup migrations alter the external database;
Helm rollback does not restore that database or search indexes. Retain and test
matching backups before changing releases. `undeploy.sh` removes the chart only;
it does not delete the namespace, external databases, indexes, or runtime Secrets.
