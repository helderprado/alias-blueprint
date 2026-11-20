# Standalone OpenSearch service

Pinned chart `2.32.0`, OpenSearch `2.19.1`. Install and use this service without
OpenMetadata, Airflow, or their configuration. It has a 20Gi PVC and internal
HTTPS endpoint `opensearch.opensearch.svc.cluster.local:9200`. It does not install
Dashboards or expose a public endpoint. The single-node footprint is not highly
available; plan replicas and storage for a larger deployment separately.

## Independent configuration and deployment

Use either the root `.env` or a component-specific file:

```sh
cp opensearch/.env.example opensearch/.env
chmod 600 opensearch/.env
# Fill only OPENSEARCH_* in that file.
ALIAS_ENV_FILE="$PWD/opensearch/.env" bash opensearch/gen-security.sh
ALIAS_ENV_FILE="$PWD/opensearch/.env" bash opensearch/deploy.sh
```

The generator requires OpenSSL, Java `keytool` and `scripts/requirements.txt`.
Nodes need a usable default StorageClass, 2Gi RAM/500m CPU for the requests and
Linux `vm.max_map_count >= 262144`. Host sysctls are not changed by this chart.

Only `OPENSEARCH_ADMIN_PASSWORD` and `OPENSEARCH_TRUSTSTORE_PASSWORD` are required
besides the default administrative username. Set the optional pair
`OPENSEARCH_APP_USER`/`OPENSEARCH_APP_PASSWORD` to create a generic application
account. The account's allowed index patterns come from
`OPENSEARCH_APP_INDEX_PATTERNS` (default `app-*`, comma-separated). It cannot
administer the security configuration. Omit both fields for admin-only bootstrap.
All passwords must contain 16..72 UTF-8 bytes. No OPENMETADATA_* values are read.

For example, a logging application may use a service account scoped to `logs-*`,
and another application can have a separate account/role provisioned through
the OpenSearch Security API. The optional bootstrap account is only an initial
account, not an automatic account for every future client. Keep client credentials
and index scopes separate when sharing the instance. Cluster-wide template
management is granted to the optional account only with an explicit `*` scope.

TLS keys, private CA, Java truststore and password hashes stay under ignored
`opensearch/runtime-creds/`. Existing material is validated and preserved. The
private CA key is never uploaded to Kubernetes; no plaintext password is put in
Helm values. Generated internal users replace the demo configuration on a fresh
security index. Changing files does not reconfigure users in an existing data
volume; later account/role changes require a separate planned Security API operation.

## Optional OpenMetadata consumer

This is a consumer configuration, not a deployment dependency of OpenSearch.
In the OpenMetadata environment file, explicitly choose the endpoint and a
provisioned account:

```sh
OPENMETADATA_SEARCH_HOST=opensearch.opensearch.svc.cluster.local
OPENMETADATA_SEARCH_PORT=9200
OPENMETADATA_SEARCH_SCHEME=https
OPENMETADATA_SEARCH_USER=your-catalog-account
OPENMETADATA_SEARCH_PASSWORD=
OPENMETADATA_SEARCH_TRUSTSTORE_FILE=opensearch/runtime-creds/truststore.jks
OPENMETADATA_SEARCH_TRUSTSTORE_PASSWORD=
```

Supply the password for that account and the password of the selected truststore.
These are deliberately separate from the server's `OPENSEARCH_*` configuration.
OpenMetadata can instead point at another supported OpenSearch service. It does
not install or remove this service. To use the initial generic account for a
dedicated catalog instance, give it the required catalog index scope before the
first bootstrap (the catalog may need `*`); do not use the admin account as a client.

If local files were produced by the earlier catalog-specific bootstrap, map the
old account into `OPENSEARCH_APP_USER`/`OPENSEARCH_APP_PASSWORD` and set its original
`*` scope. Existing `catalog.hash` and identities are read without replacing keys
or hashes. A mismatch stops the deploy; old files are never silently overwritten.

## Operations and return to a previous version

Persist and securely back up the data volume, OpenSearch snapshots, runtime Secrets,
private CA/key files, truststore password and matching repository revision.
Certificates need planned renewal before expiry; the script does not silently
replace an existing identity or certificate. Expired/changed material requires a
separate maintenance operation.

Use `scripts/UPGRADES.md` and the OpenSearch release's supported upgrade path.
An atomic Helm rollback is not an in-place data-format downgrade. Returning to an
older server may require a separate cluster and a compatible snapshot captured
before the upgrade. Do not mount newer-version data in an older server.

`undeploy.sh` removes the Helm release. It does not delete the namespace or
runtime Secrets and does not deliberately remove the PVCs. Do not delete volumes
without a verified backup. Deployment is not a substitute for a snapshot policy.

This component has been checked by local configuration/template tests only;
there was no installation or data operation against a live cluster.
