#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/versions.sh"

kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.3/cert-manager.crds.yaml

helm repo add jetstack https://charts.jetstack.io

helm repo update

helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 --install cert-manager cert-manager --repo https://charts.jetstack.io --version "$(chart_version cert-manager)" --post-renderer "$SCRIPT_DIR/scripts/locked-images.py" \
  --namespace cert-manager \
  --create-namespace --values "$SCRIPT_DIR/versions/cert-manager.values.json"

helm upgrade --atomic --timeout "${HELM_TIMEOUT:-10m}" --history-max 20 --install rancher rancher --repo https://releases.rancher.com/server-charts/stable --version "$(chart_version rancher)" --post-renderer "$SCRIPT_DIR/scripts/locked-images.py" \
  --namespace cattle-system --create-namespace \
  --set hostname={HOSTNAME_IP}.sslip.io \
  --set replicas=1 \
  --set bootstrapPassword='' --values "$SCRIPT_DIR/versions/rancher.values.json"

