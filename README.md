# alias-blueprint

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
