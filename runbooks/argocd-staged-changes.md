# Making staged manual changes without fighting ArgoCD

Every app in this cluster is GitOps-managed by ArgoCD with
`automated: {prune: true, selfHeal: true}`. That means **any `kubectl` change you
make to a managed resource is reverted within seconds** to match git. For most work
that is exactly what you want. But some operations need a *controlled sequence of
manual steps that git can't express* — e.g. a database migration where you must:
scale an app down → run SQL → swap an image → run more SQL → scale back up, with
verification between each step. ArgoCD will fight every one of those steps unless you
suspend it correctly.

This is the recurring "we're fighting Argo" problem. Here is the exact way to do it.

## The app-of-apps trap (why suspending one app isn't enough)

There is a **root app-of-apps** called `homelab` (ArgoCD Application, path `apps/`,
`repoURL` the homelab repo). It renders `apps/*.yaml`, which are themselves the
Application objects for every workload (`immich`, `media`, `baloo`, …). `homelab`
also has `selfHeal: true`.

So the Application objects are *themselves* managed resources. If you only suspend a
child app:

```bash
kubectl -n argocd patch application immich --type merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'
```

…then within seconds `homelab`'s selfHeal notices the child no longer matches
`apps/immich.yaml` (which still says `automated: {prune, selfHeal}`), **re-adds the
`automated` block, and the child immediately re-syncs to git** — reverting your manual
changes. This looks exactly like "ArgoCD undid my change for no reason." It happened
during the 2026-07-27 Immich v3 migration: the DB image swap and the `replicas=0`
scale-down were both reverted ~1s after being applied, and Immich got scaled back up
against a half-migrated database.

`homelab` has **no** `tracking-id` annotation and is not managed by anything above it,
so suspending `homelab` *does* stick.

## Procedure: suspend → change → reconcile git → re-enable

### 1. Suspend the root app-of-apps FIRST, then the child

Order matters — suspend `homelab` before the child, so `homelab` can't re-enable the
child while you work.

```bash
kubectl -n argocd patch application homelab --type merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'
kubectl -n argocd patch application immich  --type merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'

# verify BOTH stay empty for a few seconds (proves homelab isn't reverting the child)
for a in homelab immich; do
  echo -n "$a automated="; kubectl -n argocd get application $a \
    -o jsonpath='{.spec.syncPolicy.automated}{"\n"}'
done
```

Suspending `homelab` does **not** undeploy anything — it only pauses drift-correction
on the Application *objects*. Every other app keeps running and keeps its own selfHeal.
Keep the blast radius small: only touch the two apps you need.

### 2. Do the staged manual work

Now `kubectl apply` / `scale` / `patch` on the child app's resources will stick. Edit
the manifests in git *as you go* (you'll need the end-state committed anyway) and
`kubectl apply -f` the specific file at the right point in the sequence. Run SQL,
verify, proceed.

### 3. Reconcile git to the live state BEFORE re-enabling

ArgoCD syncs to **`main`**. If you re-enable auto-sync while `main` still has the old
manifests, ArgoCD will revert everything you just did. So the end-state must be on
`main` first:

```bash
git add <the specific manifests you changed>
git commit -m "…"
git push            # merge to main (this repo's target branch)
```

### 4. Re-enable auto-sync (child first, then root) and confirm no-op

```bash
kubectl -n argocd patch application immich --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
kubectl -n argocd patch application homelab --type merge \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'

# Both should report Synced/Healthy with an empty diff, since live == main.
kubectl -n argocd get application immich homelab \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status
```

If the child shows `OutOfSync` here, live and git disagree — inspect the diff
(`argocd app diff immich` or the ArgoCD UI) and fix git rather than letting selfHeal
blindly overwrite the live state.

## Notes

- **PVC resize is a resource CNPG/ArgoCD may not reconcile from a crashlooping pod.**
  During the same migration, the CNPG operator saw `spec.storage.size: 20Gi` but never
  patched the PVC requests because it couldn't read the down primary's status. The
  unblock was to patch the PVCs directly
  (`kubectl -n immich patch pvc immich-db-N -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'`);
  Longhorn (`allowVolumeExpansion=true`) then expanded online and the primary recovered.
- Related: the CLAUDE.md notes on ArgoCD selfHeal racing dynamic PVC provisioning and
  on `RespectIgnoreDifferences` — those cover the *automated* fight; this runbook covers
  the *manual staged-change* fight.
- See `runbooks/immich-vectorchord-migration.md` for the migration that motivated this.
