# Spark Operator

This Helm release controls Spark jobs in namespace `spark`. The controller runs
in `spark-operator`, uses the committed chart/image pins and admission webhook,
and has explicit CPU/memory resources. Driver accounts are prepared separately
with namespace-scoped RBAC rather than a global `edit` binding.

See [the Spark procedure](../spark/README.md) for configuration, offline preview,
installation, resource budgets, runtime Secrets, MinIO/GlusterFS integration,
image builds and the distributed smoke check.

From the repository root, after preparing the selected `ALIAS_ENV_FILE`:

```sh
bash spark-operator/deploy.sh --render
bash spark-operator/deploy.sh
bash spark/submit.sh --render
bash spark/submit.sh
```

`add-roles.sh` delegates to `spark/setup.sh` and supports `--render`.
`database-secrets.yaml` is a compatibility placeholder that creates no resources.
`persistent-volume.yaml` is a legacy node-local example for old workloads in
`spark-operator`; the current Spark procedure uses an optional existing PVC in
`spark`. No volume or permission migration is performed automatically.
