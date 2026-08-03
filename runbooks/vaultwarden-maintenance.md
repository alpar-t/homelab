# Vaultwarden compatibility and upgrades

Keep Vaultwarden close to the current stable release because official Bitwarden
clients auto-update independently. A newly updated client can require server API
behavior that the previously working Vaultwarden release does not provide. The
result may look like an empty vault even while the server, database, and older
clients remain healthy.

## Release-monitoring cadence

- Watch or subscribe to
  [Vaultwarden releases](https://github.com/dani-garcia/vaultwarden/releases).
- Review stable releases at least weekly and whenever Bitwarden clients publish
  a new monthly version.
- Treat a release note saying it is required for a Bitwarden client version as
  time-sensitive. Upgrade before that client version reaches browsers, or as
  soon as practical if browser stores have already released it.
- Also prioritize releases containing security fixes.
- Do not infer the container name or digest from the GitHub repository. Verify
  the Docker Hub tag and its Linux `amd64` image before editing the manifest.

## Recognize a compatibility incident

A client/server compatibility gap is likely when:

- two or more current browser extensions show an empty or indefinitely loading
  vault;
- an older, desktop, or mobile client still loads the same account;
- `https://vault.newjoy.ro/alive` returns HTTP 200;
- the Vaultwarden pod and both CNPG instances are ready;
- the database still contains ciphers; and
- affected extensions do not produce a new successful `/api/sync` request in
  the Vaultwarden logs.

Check the service without reading vault contents:

```bash
kubectl -n vaultwarden get deployment,pod,pvc -o wide
kubectl -n vaultwarden get cluster.postgresql.cnpg.io vaultwarden-db
kubectl -n vaultwarden top pod
kubectl -n vaultwarden logs deployment/vaultwarden \
  --since=2h --tail=2000 \
  | grep -Ei 'error|warn|panic|timeout|sync|database|pool|50[0-4]'
curl -sS -o /dev/null \
  -w 'HTTP %{http_code} total=%{time_total}s\n' \
  https://vault.newjoy.ro/alive
```

Confirm that encrypted records exist by counting them only:

```bash
kubectl -n vaultwarden exec vaultwarden-db-1 -c postgres -- \
  psql -U postgres -d vaultwarden -tAc \
  "select 'users='||count(*) from users
   union all select 'ciphers='||count(*) from ciphers
   union all select 'folders='||count(*) from folders;"
```

Do not tell users to log out, clear extension storage, or reinstall until a
working client confirms recent data is present. Unsynced local changes could be
lost.

## Audit a release before upgrading

Read the complete notes for every skipped release, not only the newest patch:

```bash
gh release view --repo dani-garcia/vaultwarden
gh release view <version> --repo dani-garcia/vaultwarden
```

Inspect the tag-to-tag database and configuration changes:

```bash
gh api repos/dani-garcia/vaultwarden/compare/<old>...<new> \
  --jq '.files[] | select(.filename | startswith("migrations/")) |
    [.filename,.status] | @tsv'

gh api repos/dani-garcia/vaultwarden/compare/<old>...<new> \
  --jq '.files[] | select(
    .filename == ".env.template" or
    .filename == "docker/entrypoint.sh" or
    .filename == "Dockerfile" or
    .filename == "src/config.rs" or
    .filename == "src/main.rs") |
    [.filename,.status,.patch] | @json'
```

Read every new PostgreSQL `up.sql` and `down.sql`. Vaultwarden embeds and runs
pending migrations automatically before creating its connection pool. Identify
whether an older server can safely run after the new migration before relying
on an image rollback.

Verify the official Docker Hub tag, manifest-list digest, and `linux/amd64`
entry. The top-level `digest` is the value pinned in the Kubernetes manifest:

```bash
curl -sS \
  "https://registry.hub.docker.com/v2/repositories/vaultwarden/server/tags/<version>/" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)
print("tag:", d["name"])
print("digest:", d["digest"])
for i in d["images"]:
    if i["os"] == "linux" and i["architecture"] == "amd64":
        print("linux/amd64:", i["digest"])'

docker manifest inspect --verbose vaultwarden/server:<version> \
  | python3 -c 'import json,sys
d=json.load(sys.stdin)
for i in d if isinstance(d,list) else [d]:
    p=i.get("Descriptor",{}).get("platform",{})
    if p.get("os") == "linux" and p.get("architecture") == "amd64":
        print("linux/amd64 descriptor:",
              i.get("Descriptor",{}).get("digest",""))'
```

The manifest must use:

```text
vaultwarden/server:<version>@sha256:<manifest-list-digest>
```

## Take a pre-upgrade backup

First verify CNPG health, continuous archiving, and the most recent scheduled
backup:

```bash
kubectl -n vaultwarden get cluster.postgresql.cnpg.io vaultwarden-db -o wide
kubectl -n vaultwarden get scheduledbackup.postgresql.cnpg.io
kubectl -n vaultwarden get backup.postgresql.cnpg.io \
  --sort-by=.metadata.creationTimestamp
```

If the `kubectl cnpg` plugin is installed, create an on-demand backup with:

```bash
kubectl cnpg backup vaultwarden-db -n vaultwarden
```

Otherwise create the equivalent native resource. Use a unique date or timestamp
in the name:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: vaultwarden-db-preupgrade-YYYYMMDD
  namespace: vaultwarden
  labels:
    app: vaultwarden
spec:
  cluster:
    name: vaultwarden-db
```

Create it and wait for completion before changing the running application:

```bash
kubectl create -f /tmp/vaultwarden-preupgrade-backup.yaml
kubectl -n vaultwarden wait \
  --for=jsonpath='{.status.phase}'=completed \
  backup.postgresql.cnpg.io/vaultwarden-db-preupgrade-YYYYMMDD \
  --timeout=10m
```

## Roll out through GitOps

Update only the pinned Vaultwarden image in
`config/vaultwarden/manifests/deployment.yaml`, then validate the change:

```bash
git diff --check
git diff -- config/vaultwarden/manifests/deployment.yaml
kubectl apply --server-side --dry-run=server \
  -f config/vaultwarden/manifests/deployment.yaml
```

The server-side dry run can report a non-fatal ownership warning for Argo CD's
`kubectl.kubernetes.io/last-applied-configuration` annotation. It must still end
with the resources reported as server-side applied in dry-run mode.

Commit and push to `main`; do not imperatively change the Deployment. Trigger
an immediate Argo CD refresh if needed:

```bash
kubectl -n argocd annotate application vaultwarden \
  argocd.argoproj.io/refresh=hard --overwrite
kubectl -n vaultwarden rollout status deployment/vaultwarden --timeout=5m
```

The Deployment uses the `Recreate` strategy, so a short interruption while the
old pod stops and the new pod starts is expected.

## Verify after upgrading

```bash
kubectl -n vaultwarden get deployment,pod -o wide
kubectl -n vaultwarden get deployment vaultwarden \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
kubectl -n vaultwarden logs deployment/vaultwarden --since=10m --tail=300
curl -sS -o /dev/null \
  -w 'HTTP %{http_code} total=%{time_total}s\n' \
  https://vault.newjoy.ro/alive
```

Confirm all of the following:

- the startup banner reports the intended version;
- the pod is ready with no restart loop;
- there are no migration, database, or configuration errors;
- any expected schema change is present in PostgreSQL;
- authenticated `/api/sync`, profile, and WebSocket requests return HTTP 200;
- a previously affected real client loads and synchronizes its vault; and
- the CNPG cluster remains healthy.

Argo CD may remain `Healthy` but `OutOfSync` because the live CNPG Cluster drops
the desired `storage.pvcTemplate` recurring-job label. That pre-existing drift
is separate from the Vaultwarden image rollout; inspect the out-of-sync resource
instead of treating the overall sync status alone as an upgrade failure.

## Roll back

If the new pod cannot start, preserve its logs, then revert the image commit and
push the revert through GitOps. Before rolling back, confirm that the old server
can tolerate every migration already applied by the new server.

Do not run migration `down.sql` manually unless the release documentation
explicitly requires it and a tested restore plan exists. Prefer restoring the
pre-upgrade CNPG backup only when the schema or data is genuinely incompatible;
ordinary additive migrations are usually safer to leave in place.

## 2026-08-03 incident

- Vaultwarden 1.36.0 was healthy, with two healthy PostgreSQL instances and 789
  encrypted cipher records.
- Two Bitwarden 2026.7 browser extensions stopped loading entries; a third,
  older client worked.
- Vaultwarden 1.37.0 release notes explicitly required 1.37.x for clients
  2026.7.0 and newer.
- The upgrade target was 1.37.1 because it also fixed invite handling.
- The only PostgreSQL migration added nullable text column
  `sso_auth.code_response_error`; it ran automatically and was verified.
- Backup `vaultwarden-db-preupgrade-20260803` completed before rollout.
- Upgrade commit `45e020b0579292ef1a023e0db07a9c4cbda65b0d` deployed successfully.
- The affected browser extension loaded its vault immediately after the
  upgrade, confirming a client/server compatibility gap rather than data loss.
