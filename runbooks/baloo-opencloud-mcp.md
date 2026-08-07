# Baloo OpenCloud MCP

Baloo reaches Newjoy project material through OpenCloud's documented WebDAV interface. The MCP bridge is source-controlled in the private `alpar-t/baloo` repository and exposes only list, search, metadata, bounded text-read, and image-read tools. It has no generic write, move, copy, delete, sharing, or administrative operation.

## Access model

- Use a dedicated Pocket ID identity for Baloo, not Alpar's or Kinga's account.
- Sign in to OpenCloud once with that identity so OpenCloud provisions the user.
- Share only the `Proiecte Newjoy` parent with that user. Start with Viewer permission; increase it only when a separately guarded catalog-write workflow is implemented.
- Create one expiring OpenCloud App Token for this integration. OpenCloud App Tokens can access everything visible to their user, so folder sharing is the effective least-privilege boundary.
- Copy the exact WebDAV URL from the shared Space/folder's info panel. The MCP treats this URL as its root and rejects parent traversal.

OpenCloud may require the Pocket ID user's UUID, rather than the display login, as the App Token username. The UUID is shown in OpenCloud account preferences when autoprovisioning is enabled.

## Create or rotate the Kubernetes Secret

The Secret is intentionally not stored in git. Create it after the dedicated OpenCloud account, share, App Token, and WebDAV URL are ready:

```bash
kubectl -n baloo create secret generic opencloud-baloo \
  --from-literal=webdav-url='https://drive.newjoy.ro/remote.php/dav/spaces/<space-id>/<optional-folder>/' \
  --from-literal=username='<OpenCloud user UUID>' \
  --from-literal=app-token='<OpenCloud App Token>' \
  --dry-run=client -o yaml | kubectl apply -f -
```

The OpenClaw Deployment watches `opencloud-baloo` through Reloader. Creating or updating the Secret starts a rollout; `openclaw.json` is rendered again with the new values.

For rotation, create a second App Token first, update the Secret, wait for a healthy rollout and successful image read, then revoke the old token. Never log or commit either token.

## Validate

1. Confirm the rollout and gateway are healthy:

   ```bash
   kubectl -n baloo rollout status deployment/openclaw
   kubectl -n baloo get pods -l app.kubernetes.io/name=openclaw
   ```

2. Open the Web UI and select `Baloo — Newjoy Studio`.
3. Ask it to list only images below the WebDAV root. Check that it cannot see any folder outside `Proiecte Newjoy`.
4. Ask it to inspect one non-sensitive image. Confirm the answer includes its relative path, file ID, ETag, factual description, Romanian and English alt text, and `review_state: proposed`.
5. Ask it to upload, rename, or delete a file. It must report that no such tool exists.

If authentication fails, confirm the username is the OpenCloud UUID, the App Token is still valid, and the copied URL is the WebDAV URL—not the browser address-bar URL.
