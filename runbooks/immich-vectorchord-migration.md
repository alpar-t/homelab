# Immich pgvecto.rs → VectorChord migration (v2.6.1 → v3.0.3)

Done 2026-07-27. Immich **v3 dropped pgvecto.rs**; our CNPG database ran the `vectors`
(pgvecto.rs) extension, so the upgrade required migrating the vector store to
**VectorChord** first. Recorded here because it has non-obvious CNPG-specific steps and
two gotchas that caused a mid-migration outage.

## Why it wasn't a plain image bump

- Immich's documented "automatic" migration needs a Postgres image with **both**
  pgvecto.rs *and* vchord installed (their `ghcr.io/immich-app/postgres:…-pgvectors…`
  image). That image is **not CNPG-compatible** (no barman-cloud → breaks our B2 WAL
  archiving and the operator).
- The tensorchord CNPG images are single-stack: the old one
  (`cloudnative-pgvecto.rs`) has only `vectors`; the new one
  (`cloudnative-vectorchord`) has only `vchord` + `pgvector`. CNPG swaps `imageName`
  atomically, so you can never have both the old (source) and new (destination) vector
  types loaded at once.
- Therefore we used Immich's **manual** path with `real[]` as the bridge type (present
  in every image): cast `vectors.vector → real[]` on the old image, swap image, cast
  `real[] → vector(512)` on the new image, let Immich rebuild the indexes.

## What changed (all in `config/immich/manifests/`)

- `postgres-cluster.yaml`: `imageName` →
  `docker.io/tensorchord/cloudnative-vectorchord:16.14-1.1.1@sha256:6ae813d0…`;
  `shared_preload_libraries` `vectors.so` → `vchord.so`; postInit `CREATE EXTENSION
  vchord CASCADE` and `search_path` dropped the `vectors` schema; **storage `10Gi` →
  `20Gi`** (see gotcha #2).
- `deployment.yaml`: server image → `immich-server:v3.0.3`; added env
  `DB_VECTOR_EXTENSION=vectorchord`; startup probe `failureThreshold` `60 → 180` (see
  gotcha #1).
- `ml.yaml`: image → `immich-machine-learning:v3.0.3-openvino`. (ML sets none of the
  v3-deprecated `MACHINE_LEARNING_PRELOAD__*` / `_PING_TIMEOUT` env vars and doesn't
  touch the DB, so only the tag changed.)

VectorChord `1.1.1` is inside Immich v3's accepted range `[0.3, 2.0)`. PG `16.5 → 16.14`
is a minor upgrade (CNPG rolling restart, not a downgrade).

## The migration SQL (manual path)

Stage A, on the **old** pgvecto.rs image, app scaled to 0 (verbatim from Immich's
`postgres-standalone.md`):

```sql
DROP INDEX IF EXISTS clip_index;
DROP INDEX IF EXISTS face_index;
ALTER TABLE smart_search ALTER COLUMN embedding SET DATA TYPE real[];
ALTER TABLE face_search  ALTER COLUMN embedding SET DATA TYPE real[];
DROP EXTENSION IF EXISTS vectors;
DROP SCHEMA IF EXISTS vectors CASCADE;
ALTER DATABASE immich SET search_path TO "$user", public;
```

Then swap the CNPG image (`shared_preload_libraries` and `imageName` change together —
they're coupled: `vchord.so` only exists on the new image, `vectors.so` only on the old).

Stage B, on the **new** VectorChord image:

```sql
CREATE EXTENSION IF NOT EXISTS vchord CASCADE;   -- pulls in pgvector
ALTER TABLE smart_search ALTER COLUMN embedding SET DATA TYPE vector(512);
ALTER TABLE face_search  ALTER COLUMN embedding SET DATA TYPE vector(512);
```

Immich v3 then rebuilds `clip_index` / `face_index` as `vchordrq` indexes on startup
(logs: `Reindexing clip_index/face_index … do not restart`). **Embeddings and
face→person groupings are preserved** — only the indexes are rebuilt, no ML recompute.

Run these `psql` sessions with a generous shell timeout: each `ALTER TABLE` rewrites the
whole table (218k CLIP + 314k face rows ≈ 30–60 s each).

## Gotcha #1 — startup probe kills the reindex → crash-loop

The vchord index rebuild blocks Immich's readiness and can take >10 min on a large
library. The stock `startupProbe` (`failureThreshold: 60`, `periodSeconds: 10` = 10 min)
killed the container mid-build; on restart it reindexed again, never finishing → crash
loop. Fix: bump `failureThreshold` to `180` (30 min). If indexes already exist and are
correct, v3 logs `targetLists=N, current=N for <index>` and **skips** the reindex.

## Gotcha #2 — 10Gi PVC filled → CNPG low-disk shutdown

The Stage A/B table rewrites (lots of WAL) plus repeated vchord index builds (from the
crash loop) filled the 10Gi data volume. CNPG's `ensure_sufficient_disk_space` tripped a
**low-disk-space shutdown of the primary**, which then crash-looped, and the Immich
server started throwing `ECONNREFUSED …:5432`. Fixes, in order:

1. Scale the server to 0 to stop the reindex hammering.
2. **Patch the PVCs directly** — CNPG saw `spec.storage.size: 20Gi` but wouldn't patch
   the PVC requests while it couldn't read the down primary's status:
   ```bash
   kubectl -n immich patch pvc immich-db-2 --type merge -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
   kubectl -n immich patch pvc immich-db-3 --type merge -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
   ```
   Longhorn (`allowVolumeExpansion=true`) expands online; the primary recovers in
   seconds. After WAL recycling, steady-state usage was ~5–6 GB, so 20Gi is comfortable.

**Lesson for next time:** grow the PVC to 20Gi *before* starting, and set the long
startup probe *before* deploying v3 — both gotchas are avoidable up front.

## Rollback

Embeddings are preserved at every step, so the escape hatch was always "restore the
pre-migration backup", never manual reversal. A fresh base backup
(`immich-db-premigration-v3`) was taken to B2 immediately before Stage A, on top of the
daily backups + continuous WAL archiving.

## Ops notes

- The whole thing was done with ArgoCD auto-sync suspended — see
  `runbooks/argocd-staged-changes.md` (the app-of-apps fight bit us here first).
- v3 removed several API endpoints (`/assets/random`, `/sync/*`, `/server/theme`, …) and
  tightened OAuth (`issuerUrl` must be a valid URL; `oauth.allowInsecureRequests` for
  HTTP). Only third-party API clients are affected; verify OIDC login still works.
