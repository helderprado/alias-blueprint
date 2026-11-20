# Standalone Apache Pinot service

Official chart `1.0.0`, with server image explicitly fixed to Pinot `1.4.0` rather
than the upstream chart's nightly-image default. ZooKeeper is fixed to `3.9.3`.
All images use immutable digests. This service is independent of Trino,
OpenMetadata and Airflow.

The compact default includes one controller, broker and server, plus a persistent
single-node ZooKeeper. Controller and server data are on PVCs; ZooKeeper data and
transaction logs are persistent. A usable default StorageClass is required, or set
`PINOT_STORAGE_CLASS`. The profile requests about 5Gi memory total; it is not an
HA or production capacity sizing. Minions and public endpoints are disabled.

## Deploy independently

```sh
cp pinot/.env.example pinot/.env
# Optionally set the StorageClass, cluster name and trusted client namespaces.
ALIAS_ENV_FILE="$PWD/pinot/.env" bash pinot/deploy.sh
```

There are no required Trino or OpenMetadata variables. Leave `PINOT_ZOOKEEPER_URL`
empty for the bundled ZooKeeper; set a supported external ZooKeeper connection
string to disable that bundle. This profile does not configure external ZooKeeper
SASL credentials. The namespace and access policy are created before Helm install.

**Access profile:** private single-tenant HTTP, without Pinot API authentication.
All services are ClusterIP. NetworkPolicy permits Pod traffic within the dedicated
`pinot` namespace and denies other namespaces by default. Only explicitly listed
`PINOT_ALLOWED_NAMESPACES` can reach controller 9000 and broker 8099; ZooKeeper and
server admin/data ports are not opened to them. This requires CNI enforcement.
Do not put untrusted workloads in this namespace or expose it through public
Ingress/LoadBalancer. Configure reviewed Pinot authentication/TLS or a trusted
security gateway before extending that trust boundary. This profile does not
claim to implement Pinot TLS, per-user authorization or multi-tenant isolation.

For an operator's local controller tunnel:

```sh
kubectl -n pinot port-forward service/pinot-controller 9000:9000
```

Use `http://127.0.0.1:9000` for the controller UI/API. Create your own schema/table
and load segments or configure a stream source. For this one-server footprint,
start table replication at one; no synthetic tables, Kafka cluster, source-system
accounts or live data ingestion are automatically provisioned. The controller
endpoint is `http://pinot-controller.pinot.svc.cluster.local:9000`; the broker
query endpoint is `http://pinot-broker.pinot.svc.cluster.local:8099`.

## Optional Trino consumer

Set `PINOT_ALLOWED_NAMESPACES=trino` explicitly, then configure the Pinot catalog
in Trino using `../trino/catalogs.example.json`. That example sends queries through
the broker instead of opening server ports for direct segment queries. You may
instead use Pinot clients independently, without deploying Trino or the catalog.

## Persistence and version changes

Keep backups of controller deep-store data, server segments, ZooKeeper state and
the matching chart/image/configuration revision. Use supported Pinot upgrade paths.
Helm rollback does not restore data formats, table changes or ZooKeeper contents.
Do not start an older image on newer data without a verified supported restore
procedure. See `scripts/UPGRADES.md`.

`undeploy.sh` uninstalls the release; it does not deliberately delete PVCs,
namespaces or the retained NetworkPolicy. Deleting those is a separate operation.
Local configuration and template checks are not a live cluster installation.
