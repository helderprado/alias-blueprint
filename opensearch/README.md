# OpenSearch backend for OpenMetadata

Pinned chart `2.32.0`, OpenSearch `2.19.1`. This dedicated single-node deployment
provides the catalog's search indexes. It has a 20Gi PVC and ClusterIP Service
`opensearch.opensearch.svc.cluster.local:9200`, uses HTTPS and authentication,
and does not install Dashboards or expose a public endpoint. A single node is
not highly available; it is the compact footprint for independent deployment.

## Bootstrap and deploy

1. Copy/fill the root `.env` as documented in `scripts/README.md`:
   `OPENSEARCH_ADMIN_USER`, `OPENSEARCH_ADMIN_PASSWORD`,
   `OPENSEARCH_TRUSTSTORE_PASSWORD`, `OPENMETADATA_SEARCH_USER`,
   `OPENMETADATA_SEARCH_PASSWORD`. Passwords must contain 16..72 UTF-8 bytes;
   the admin and catalog usernames must differ. No default password is provided.
2. Install the pinned Python dependencies in `scripts/requirements.txt`. The
   generator also needs OpenSSL and Java `keytool`. Nodes need a usable default
   StorageClass and sufficient resources (request 2Gi RAM and 500m CPU). Configure
   Linux `vm.max_map_count >= 262144` on eligible nodes. This chart deliberately
   does not modify host sysctls with a privileged container.
3. Run `bash opensearch/gen-security.sh`. It generates a private CA, a server key
   and certificate with the internal Service DNS names, a Java truststore, and
   bcrypt hashes for two distinct accounts. All files stay in ignored
   `opensearch/runtime-creds/` with restrictive permissions. The CA private key
   is never uploaded to Kubernetes. Existing material is validated and preserved.
4. Run `bash opensearch/deploy.sh`. It validates local inputs, creates the
   namespace and missing Secrets, then performs an atomic Helm upgrade/install.
5. Keep the generated truststore path in `OPENMETADATA_SEARCH_TRUSTSTORE_FILE`,
   and run the OpenMetadata bootstrap/deployment as documented in that directory.
   Its deployment imports the truststore and password via Secrets, without
   disabling TLS certificate checks. PostgreSQL and OIDC remain prerequisites.

The cluster initialization uses only the generated internal accounts and role
mappings. The default demo configuration is disabled. The catalog account can
manage application indexes and query cluster health; it cannot administer the
security configuration. Index permissions cover this dedicated instance's
application indexes, so do not mix unrelated applications into this instance.
The separate bootstrap admin can administer the service. Its plaintext password
is not supplied to OpenMetadata or the Helm values.

The initial security files seed a fresh security index; they do not reconfigure
accounts in an existing OpenSearch data volume. Existing local material and
Kubernetes Secret changes are refused during ordinary deploy. Manage a later
account change as a separate planned security configuration operation.

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
