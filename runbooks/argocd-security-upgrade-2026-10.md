# Argo CD 3.4.4 to 3.4.12 security update

Argo CD is bootstrapped from the upstream `install.yaml`, outside the homelab
app-of-apps. The running 3.4.4 image has critical CVE-2026-77459 (AppProject
hook restriction bypass). The upstream 3.4.10 security release fixes it;
3.4.12 is the latest patch on the existing 3.4 branch as of 2026-10-23.
The verified Linux amd64 3.4.12 image is
`quay.io/argoproj/argocd:v3.4.12@sha256:da43096503915aa78980da13ffaad832247b90821744cd9ce8bdce8e43bded71`.
Trivy reports two remaining critical advisories in that image, down from
three in 3.4.4, and no longer reports CVE-2026-77459.

The reviewed server-side diff of the official 3.4.12 install against the live
installation includes exactly seven Argo CD workloads. Aside from apply metadata,
it changes their Argo CD images,
digest pins for the existing Dex and Redis images, and one repo-server
`/home/argocd/params` mount. It changes no Service, Ingress, ConfigMap,
Secret, RBAC object, or CRD. Recheck this diff immediately before applying;
stop if its scope grows.

## Prepare and preflight

Confirm all Argo CD pods are Ready, the `homelab` Application is Synced and
Healthy, and the private-access controls in `runbooks/argocd-access.md` still
hold. Record current pod images and application status.

```bash
kubectl -n argocd get pods
kubectl -n argocd get application homelab -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status'
kubectl -n argocd get ingress argocd-server
kubectl -n cloudflared get configmap cloudflared-config -o jsonpath='{.data.config\.yaml}'
```

The Ingress lookup must be `NotFound`, and the first tunnel rule for
`argocd.newjoy.ro` must return `http_status:404`.

Download the immutable upstream release manifest and use the repository helper
to verify its SHA-256 and pin all image references. The helper accepts only
the reviewed 3.4.12 and 3.4.4 source manifests. Its image digests were
resolved with `scripts/resolve-container-image.py` for Linux amd64.

```bash
curl -fsSL https://raw.githubusercontent.com/argoproj/argo-cd/v3.4.12/manifests/install.yaml \
  -o /private/tmp/argocd-v3.4.12-install.yaml
python3 scripts/prepare-argocd-security-upgrade.py v3.4.12 \
  /private/tmp/argocd-v3.4.12-install.yaml /private/tmp/argocd-v3.4.12-pinned.yaml
kubectl diff --server-side --force-conflicts -n argocd \
  -f /private/tmp/argocd-v3.4.12-pinned.yaml
```

`kubectl diff` exits 1 when it finds changes. Inspect all seven workload diffs
before continuing. It must show only the fields described above; any other
change requires a new review. The pinned file's expected SHA-256 is
`1a42c9075af9e0ca45fcf3286485f30ae046a60f8c71a0383eebdd0e6ff4898e`.

## Apply and verify

```bash
kubectl apply --server-side --force-conflicts -n argocd \
  -f /private/tmp/argocd-v3.4.12-pinned.yaml
kubectl -n argocd rollout status deployment/argocd-repo-server --timeout=5m
kubectl -n argocd rollout status statefulset/argocd-application-controller --timeout=5m
kubectl -n argocd rollout status deployment/argocd-server --timeout=5m
kubectl -n argocd rollout status deployment/argocd-applicationset-controller --timeout=5m
kubectl -n argocd rollout status deployment/argocd-notifications-controller --timeout=5m
kubectl -n argocd rollout status deployment/argocd-dex-server --timeout=5m
kubectl -n argocd rollout status deployment/argocd-redis --timeout=5m
kubectl -n argocd get pods
kubectl -n argocd get application homelab -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status'
```

Verify the application inventory remains Synced/Healthy and test the private
port-forward and public 404 checks in `runbooks/argocd-access.md`. Check the
security scanner's next report for the new digest. After a successful rollout,
update the bootstrap version in `genesis/README.md` from 3.4.4 to 3.4.12 so a
rebuild does not restore the vulnerable version.

## Rollback

Use the exact previous release manifest and digest-pinning helper. This
restores the previous repo-server mount layout as well as the image versions.
Rollback reintroduces CVE-2026-77459, so use it only if the new release breaks
Argo CD and investigate the failure immediately.

```bash
curl -fsSL https://raw.githubusercontent.com/argoproj/argo-cd/v3.4.4/manifests/install.yaml \
  -o /private/tmp/argocd-v3.4.4-install.yaml
python3 scripts/prepare-argocd-security-upgrade.py v3.4.4 \
  /private/tmp/argocd-v3.4.4-install.yaml /private/tmp/argocd-v3.4.4-pinned.yaml
kubectl diff --server-side --force-conflicts -n argocd \
  -f /private/tmp/argocd-v3.4.4-pinned.yaml
kubectl apply --server-side --force-conflicts -n argocd \
  -f /private/tmp/argocd-v3.4.4-pinned.yaml
```

Wait for the same seven rollouts and recheck application and access health.
