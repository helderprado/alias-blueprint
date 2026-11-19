# Component versions

These entries describe repository files, not a measured running environment.
Unknown values are retained explicitly; no installation was performed.

| Component | Version or status | Evidence |
|---|---|---|
| K3s | `v1.34.13+k3s1` | `install-k3s.sh` |
| kubectl | Not confirmed | No recorded client version |
| Helm client | Not pinned; installer accepts `--version` | `get_helm.sh` |
| Rancher | Chart version not pinned | `install-rancher.sh` |
| cert-manager CRDs | `v1.13.3`; chart version not pinned | `install-rancher.sh` |
| Airflow deployment chart | Stable release `1.16.0` by default; override with `AIRFLOW_CHART_VERSION` | `airflow/deploy.sh`, official repository `https://airflow.apache.org`; legacy bundled chart is unused |
| Airflow custom image base | `2.6.2` | `airflow/image/Dockerfile`; custom base; validate compatibility with the selected chart |
| JupyterHub custom hub base | `3.2.1` | `jupyterhub/images/hub/Dockerfile` |
| Spark and Spark Operator | Chart versions not confirmed | `spark/`, `spark-operator/` |
| MLflow | Chart version not confirmed | `mlflow/` |
| Superset | Chart version not pinned; main image tag empty | `superset/values.yaml` |
| Registry credential generator | `httpd:2.4-alpine` | `registry/gen-pass.sh` |
| Registry chart | Chart version not pinned | `registry/deploy.sh` |
| PostgreSQL | `13-alpine` and `14` | `databases/prod-db/deploy.yaml`, `databases/superset-db/deploy.yaml` |
| MySQL | `5.7.28` | `databases/mlflow-db/deploy.yaml` |
| pgAdmin | Image tag not pinned | `pgadmin/deployment.yaml` |
| Homepage | `v0.7.0` | `homepage/values.yaml` |

## Configuration status

`.env.example` is a template only. The current scripts do not automatically
load `.env`. `install-k3s.sh` accepts exported `K3S_VERSION` (or
`INSTALL_K3S_VERSION`) and `K3S_CONFIG`, with a fixed version and the
repository-local configuration as defaults;
registry scripts request credentials interactively. The README template's
statements about environment loading and validation are not implemented by
these scripts as a whole. The K3s installer validates the release format,
configuration file, and required commands before contacting the installer.

## Third-party licenses

The blueprint license is Apache-2.0. A component-by-component license inventory
has not been verified and remains pending author confirmation; third-party
components retain their respective licenses and notices.
