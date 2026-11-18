#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
helm install airflow "$SCRIPT_DIR/repo/airflow-1.16.0-dev.tgz" --namespace airflow --values "$SCRIPT_DIR/values.yaml"
