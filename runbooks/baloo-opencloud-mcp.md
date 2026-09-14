# Baloo OpenCloud MCP

Baloo reaches Newjoy project material through OpenCloud's documented WebDAV
interface. The MCP bridge is source-controlled in the private `alpar-t/baloo`
repository. General agents receive only list, search, metadata, bounded
text-read, and image-read tools. The Newjoy organizer additionally receives
bounded directory, move, text/YAML, and organization-state operations. The
Newjoy Technical Drafter uses a separate deterministic service for bounded
binary import, immutable PDF review candidates, and immutable issued PDFs. No
agent receives generic deletion, sharing, or administrative operations. The
Website Manager's generated JPEG previews are also stored immutably below
`Execution/Website Previews/` and attached through the shared browser bridge;
it cannot invoke drafter tools.

## Access model

- Use a dedicated Pocket ID identity for Baloo, not Alpar's or Kinga's account.
- Sign in to OpenCloud once with that identity so OpenCloud provisions the user.
- Share only the `Proiecte Newjoy` parent with that user. The account needs
  permission to create and move content because organizer and technical-plan
  writes are constrained in code and by per-agent tool allowlists rather than
  by a separate OpenCloud identity.
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

The OpenClaw and technical-plan Deployments watch `opencloud-baloo` through
Reloader. Creating or updating the Secret starts their rollouts;
`openclaw.json` is rendered again with the new values.
The Python bridge loads its service code at process startup: changes to
`technical-plan-api.py` require a rollout of `deployment/technical-plan-api`
after git-sync reaches the desired revision. Agent prompts, shared skills, and
the stdio MCP adapter continue to update through the normal git-sync path.

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
5. Ask Alpar to upload, rename, or delete a file. It must report that no such
   tool exists. Newjoy Studio may perform only its explicitly allowlisted
   organization writes.
6. Select `Baloo — Newjoy Technical Drafter`. Confirm it is Astra with high
   reasoning, has no messaging binding, and can see both technical-plan skills.
7. In a disposable project, import one bounded source, render a working PDF,
   inspect every returned PNG page, and attach the exact working OpenCloud PDF
   in the browser. Confirm a different agent cannot invoke either browser tool.
8. Approve an issue revision, publish it below
   `Execution/Technical Plans/Issued/<scope>/`, and compare the reported
   SHA-256 with a fresh OpenCloud download. Reusing the revision with different
   bytes, skipping a room/export, or skipping a preview page must fail.
9. Select Website Manager and preview a saved story. Its renderer must return
   `browserPreviewPath`; `preview_opencloud_image` must attach that JPEG as an
   actual image. Uploads are downloaded again and hash-compared before a
   successful `chat:message:files` event is acknowledged. A tool-returned MCP
   image or a prose delivery statement alone does not satisfy this check.

If authentication fails, confirm the username is the OpenCloud UUID, the App Token is still valid, and the copied URL is the WebDAV URL—not the browser address-bar URL.
