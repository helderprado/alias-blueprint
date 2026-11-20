# Standalone Trino SQL service

Trino chart `1.45.0`, server `484`, coordinator plus one worker by default. Both
chart release and image digest are pinned. This service does not install or
require Pinot, OpenMetadata, Airflow, MLflow or a metastore to start. The default
TPC-H/TPC-DS catalogs allow synthetic SQL queries without a data-source account.

## Configure and deploy

```sh
cp trino/.env.example trino/.env
chmod 600 trino/.env
# Fill TRINO_USER, TRINO_PASSWORD and TRINO_SHARED_SECRET.
ALIAS_ENV_FILE="$PWD/trino/.env" bash trino/gen-security.sh
ALIAS_ENV_FILE="$PWD/trino/.env" bash trino/deploy.sh
```

Install `scripts/requirements.txt` in the Python environment used by the scripts;
bootstrap also needs OpenSSL. Passwords require 16..72 UTF-8 bytes. Generate the
shared secret once with `openssl rand -hex 32`, put it in `.env` and retain it.
The generator creates a bcrypt password file and a private CA/server certificate
under ignored `runtime-creds/`, with mode 600, and preserves existing material.
No administrative or database password is shipped. The CA private key is never
uploaded to Kubernetes. Secret changes during ordinary deploy are refused.

The compact coordinator/worker footprint requests about 6Gi memory total. Adjust
resources and query memory together before running large workloads. The namespace
and Secrets are created after validation; the deployment uses atomic Helm upgrade.
The official chart checksum is verified first. Its CI-only connection-test hook,
which assumes upstream demo login/certificate names, is removed from the temporary
archive. No application template is changed; use the explicit SQL smoke query
below instead of that upstream Helm test.
Trino does not store your source datasets in its Pods. Worker restarts may interrupt
in-flight queries; atomic deployment is not a guarantee of uninterrupted queries.

The API is `https://trino.trino.svc.cluster.local:8443`. For a local SQL session:

```sh
kubectl -n trino port-forward service/trino 8443:8443
# In another terminal, use the matching Trino CLI, which prompts for the password:
trino --server https://localhost:8443 --user YOUR_USER --password \
  --truststore-path trino/runtime-creds/ca.pem
```

Then run `SELECT count(*) FROM tpch.tiny.nation;`. The CLI must support the selected
release; no CLI binary is downloaded automatically. Browser/client connections
must trust the generated CA; do not disable certificate validation.

A NetworkPolicy allows inter-Pod traffic within the dedicated namespace. Extra
client namespaces must be listed in `TRINO_ALLOWED_NAMESPACES`; they receive access
only to HTTPS port 8443. The HTTP listener remains for discovery/internal traffic,
and PASSWORD authentication does not allow insecure HTTP client login. Network
isolation requires a CNI that enforces NetworkPolicy. No public ingress is created.
Internal worker/coordinator traffic uses the private network, not full mutual TLS.

## Optional data-source catalogs

Set `TRINO_CATALOGS_FILE` to a local JSON object mapping catalog names to their
`.properties` content. A source example is `catalogs.example.json`: copy it under
ignored `trino/runtime-creds/` before adding any connection credentials. The file
is stored as a Kubernetes Secret and mounted on both coordinator and workers;
its contents are not Helm values. When selected, this replaces the active catalog
directory, so include every catalog you need. Changes to an existing catalog Secret
require an explicit configuration/Secret change plan, with backup and rollback.

The optional Pinot example fixes the broker Service endpoint and forbids direct
segment queries, so it only needs controller/broker access. To enable it, deploy
Pinot separately and set `PINOT_ALLOWED_NAMESPACES=trino` in the Pinot environment.
Nothing connects the two services automatically. Other Trino connectors can use
your own independently provisioned databases, object stores and metastores.

See `scripts/UPGRADES.md` before changing versions. `undeploy.sh` removes the Helm
release, leaving the namespace, access policy and runtime Secrets for explicit
management. No live deployment or source-data query was performed during addition.
