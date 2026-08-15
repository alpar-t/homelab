# Newjoy portal

`https://portal.newjoy.ro` is a Pocket ID-protected directory of household and
homelab services. It is intentionally a static site with a small authentication
edge rather than a stateful dashboard application.

## Architecture

```text
browser
  │
  ▼
ingress-nginx ── auth subrequest ──► oauth2-proxy ── OIDC ──► Pocket ID
  │                                      │
  │ verified X-Auth-Request-* headers    │ signed session cookie
  ▼                                      │
nginx portal image ◄────────────────────┘
  │
  └─ maps the verified groups header to one internal JSON catalog
```

The browser receives the common HTML/CSS/JavaScript shell and requests
`/catalog.json`. Portal nginx maps that stable URL to exactly one catalog:

| Pocket ID group | Catalog | Contents |
|---|---|---|
| `advanced_apps` | `admin.json` | Household services plus operations and media administration |
| `family_users` | `family.json` | Household services |
| Neither | `base.json` | Pocket ID account links only |

The admin match is evaluated first and its catalog is a superset of the family
catalog. Direct requests to `/catalog/admin.json` and the other backing files
are rejected by nginx's `internal` location.

Members of `advanced_apps` get a **View as** selector for reviewing the family,
Baloo-access, and no-group experiences. nginx validates the real Pocket ID
group before honoring `?view=`; non-admin users cannot reveal another catalog
by constructing that query parameter themselves. The Baloo view is
documentation, not a Pocket ID user role.

This is discovery policy, not authorization for the linked services. Each
service must continue to enforce its own Pocket ID group policy or application
permissions. Hiding a link in the portal does not revoke access to its URL.

The UI, catalogs, icons, and nginx policy are baked into one public GHCR image.
The source repository is public too, and anonymous image pulls avoid a
long-lived registry credential in the cluster. The pod never receives source
files through ConfigMaps.

## First deployment

The portal depends on the shared Pocket ID OIDC provisioner, so Pocket ID must
already be healthy before the image-backed Deployment rolls out. A separate
idempotent PreSync hook generates oauth2-proxy's cookie key; it does not depend
on a change to the shared provisioner.

1. Sync the root `homelab` app, or apply `apps/portal.yaml` and sync `portal`.
2. Open Pocket ID → OIDC Clients → `portal` → Allowed User Groups. Permit the
   existing `family_users` and `advanced_apps` groups. Pocket ID creates new clients with no
   allowed users, so sign-in will fail until this is set.
3. Open `https://portal.newjoy.ro` and sign in once as a member of each group.

The provisioner creates the confidential client with this callback:

```text
https://portal.newjoy.ro/oauth2/callback
```

It stores `client_id` and `client_secret` in `portal/portal-oidc`. The following
PreSync hook stores oauth2-proxy's encryption key in `portal/portal-cookie`. No
credential belongs in Git.

## Edit the catalog

Catalogs live under `config/portal/manifests/assets/catalog/`. Keep the admin
catalog as a superset of the family catalog. Cards lead with the human
capability, not the implementation. Put the product name in `product`; the UI
renders it as a smaller label and includes it in search. A basic card has this
shape:

```json
{
  "name": "Pictures & albums",
  "product": "Immich",
  "description": "Browse, search, back up, and share the family photo and video library.",
  "url": "https://photos.newjoy.ro",
  "icon": "photos",
  "accent": "#7f92ff",
  "network": "anywhere",
  "tags": ["Immich", "photos", "videos"]
}
```

Use `"network": "home"` for LAN/Tailscale-only links. The UI renders that
constraint but does not proxy the destination.

Maturity and direct Baloo access are centralized in
`config/portal/manifests/assets/capability-policy.json`, keyed by the exact
`product` string. `maturity` is either `stable` or `experimental`. `baloo`
records whether an agent has direct tool access; use `detail` for meaningful
limits such as `Read-only` or `Alpar only`. Do not mark ordinary web research
as direct Baloo access.

```json
"OpenCloud": {
  "maturity": "stable",
  "baloo": {"available": true, "detail": "Read-only"}
}
```

Add an optional `setup` object when a phone app, browser extension, server URL,
or non-obvious first-run step materially improves the experience. `steps` are
rendered as an ordered list, `links` open official setup/download pages in a new
tab, and `groups` can document group-to-agent access. Keep secrets and personal
phone numbers out of catalogs.

```json
"setup": {
  "label": "Set up automatic phone backup",
  "steps": ["Install the Immich app.", "Use https://photos.newjoy.ro as the server."],
  "links": [
    {"label": "Immich mobile guide", "url": "https://docs.immich.app/features/mobile-app/"}
  ]
}
```

The Baloo card currently shows the same complete assistant lineup for
`family_users` and `advanced_apps`. WhatsApp still routes each private or group
conversation to its configured agent. Update both catalog entries if either
portal group's advertised lineup changes.

Changes under `manifests/assets/` trigger the portal image workflow. It publishes
an immutable commit-tagged image, resolves its registry digest, and commits the
verified `tag@digest` reference back to the Deployment. ArgoCD then performs a
normal rolling update.

### Baloo access documentation

`baloo.json` documents the current per-agent tool policy from the private
`../baloo/openclaw/openclaw.json` repository. The detailed capability and hard
limit sections describe the `alpar` agent; the final section summarizes how the
other agents differ.

Treat Baloo's `openclaw.json` as the source of truth. Whenever an agent's
`tools.allow`, `tools.deny`, MCP registration, or network boundary changes,
review the Baloo catalog in the same change window. Do not infer access from an
MCP server merely being registered globally—only an agent's explicit allowlist
grants it.

## Local preview

No cluster, Pocket ID account, container runtime, or package installation is
needed:

```bash
python3 scripts/preview-portal.py
```

Open `http://127.0.0.1:8080`. The preview simulates an `advanced_apps` member,
so the **View as** selector can exercise every catalog. Use another port with
`--port 8081`. The cards still point to real services; the preview does not
proxy or mock those destinations.

The header theme toggle switches between the designed light and dark palettes
and persists the choice in browser-local storage. On the first visit, before a
choice exists, the portal follows `prefers-color-scheme`. `theme.js` runs before
the stylesheet so the selected theme is applied before the first paint.

## Container image and ARC workflow

`.github/workflows/portal-image.yaml` runs on the repository-scoped
`homelab-runners` ARC scale set. The runner remains unprivileged and has no
Docker socket. The workflow downloads a pinned, checksummed `crane` release,
creates a deterministic layer containing the static assets and nginx policy,
and appends it to the pinned official nginx base image for `linux/amd64`.
The build injects the source commit SHA into the CSS, JavaScript, and icon URLs;
nginx also serves the tiny portal shell with `Cache-Control: private, no-store`
and disables validators. This prevents a browser from mixing assets from two
immutable image revisions after a rollout.

The image is pushed publicly as
`ghcr.io/alpar-t/newjoy-portal:sha-<commit>@sha256:<digest>`. After checking that
the digest exists in the registry, the workflow renders the image-backed
Deployment from `config/portal/image/deployment.yaml.template` and commits only
the Deployment update. Its path filter excludes that generated file,
preventing a build loop.

For the first deployment, merge the scale set, workflow, portal source, and
image templates before adding `apps/portal.yaml`. The first workflow run
publishes the image and commits the digest-pinned Deployment. Only then add the
ArgoCD Application. Argo CD deploys the top-level YAML files as a plain manifest
directory; no Kustomize layer is involved. This keeps every deployable revision
valid and ensures a ConfigMap-backed portal is never needed. Subsequent asset
changes only replace the immutable image reference.

`config/portal/image/Dockerfile` documents the equivalent conventional build,
but ARC deliberately uses the daemonless path so the runner does not need a
privileged Docker-in-Docker sidecar.

## Validate

Before committing:

```bash
for catalog in config/portal/manifests/assets/catalog/*.json; do
  jq empty "$catalog"
done

node --check config/portal/manifests/assets/app.js
node --check config/portal/manifests/assets/theme.js
kubectl create --dry-run=client --validate=false -f config/portal/manifests/
```

After ArgoCD syncs:

```bash
kubectl get pods,ingress -n portal
kubectl logs -n portal deployment/oauth2-proxy
kubectl logs -n portal deployment/portal
curl -I https://portal.newjoy.ro
```

An unauthenticated request should redirect through `/oauth2/start` to Pocket
ID. After authentication, check that `family_users` sees the family catalog and
`advanced_apps` sees the operations sections and view selector. Confirm that requesting
`https://portal.newjoy.ro/catalog/admin.json` returns 404.

## Troubleshooting

- `portal-oidc` missing: check the `portal-oidc-client` PreSync Job in the
  `pocket-id` namespace and confirm `pocket-id-api-key` exists.
- `portal-cookie` missing: check the `portal-cookie-secret` PreSync Job in the
  `pocket-id` namespace and confirm the `portal` namespace exists.
- `ImagePullBackOff`: confirm the manifest's immutable GHCR reference exists
  and the `newjoy-portal` package remains publicly pullable.
- Portal image workflow remains queued: confirm the `homelab-runners` listener
  is connected and the workflow uses `runs-on: homelab-runners`.
- Login says the user is not allowed: add the user's group under the portal
  client's Allowed User Groups in Pocket ID.
- Everyone sees only account links: confirm oauth2-proxy requests the `groups`
  scope, has `--set-xauthrequest=true`, and ingress forwards
  `X-Auth-Request-Groups`.
- A local link fails remotely: connect Tailscale; `192.168.1.x` destinations
  intentionally do not pass through Cloudflare or the portal.
