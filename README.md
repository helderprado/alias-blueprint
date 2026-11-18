# alias-blueprint

## Installation

Run `bash install-k3s.sh` from any directory. The script pins K3s to
`v1.34.13+k3s1` and loads this repository's `k3s-config.yaml`.
This version is a reproducibility baseline; the complete stack still needs
validation on a fresh cluster.

Run `bash airflow/deploy.sh` to install the bundled Airflow chart using its
repository-local values file.

## Registry credentials

Previously committed credentials must be treated as compromised. Removing them
from Git does not revoke access to a running registry.

1. Run `bash registry/gen-pass.sh` on a trusted machine with Docker. Choose a new,
   non-admin username and a unique password of at least 16 characters.
2. Run `bash registry/deploy.sh` with Helm configured for the target cluster.
   This replaces the registry authentication file, removing the old account.
3. Update image pull secrets and CI credentials used by registry clients.
4. Verify that the old credentials are rejected and the new credentials work.

The generated bcrypt file stays in ignored `registry/registry-creds/`; plaintext
credentials are not saved by the generator. Helm stores release configuration in
cluster Secrets, so restrict access to those Secrets.

History cleanup and remote publication are separate steps and must include all
branches and tags that contain the exposed files or inline credentials.

## License and citation

The blueprint code is licensed under Apache-2.0; see `LICENSE`. Bundled third-party
components retain their own licenses and notices. Citation metadata for this
software are provided in `CITATION.cff`.
