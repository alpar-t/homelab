# Newjoy website staging and source integration

Website/importer source: private alpar-t/newjoy-website. Homelab owns runner
storage, credential mounts, staging protection, and GitOps image references.
The separate portal is documented in newjoy-portal.md.

## Staging and authentication

The initial sample-content image is deployed and Argo reports Synced/Healthy.
The owner verified login at staging.newjoy.ro on 9 September 2026.
Authentication is entirely the existing oauth2-proxy + Pocket ID infrastructure
client. Any Pocket ID login is allowed: isGroupRestricted=false, no group
allowlist. No authentication code belongs in Astro, and no further Pocket ID
integration is needed for OpenCloud content.

Signed-out root, assets, and environment requests redirect through the proxy.
Staging responses use private, no-store and no-index headers. Keep the OIDC
provisioner's stdout suppression, which prevents Secret response logging.
Do not interpret deployment health as visual-design acceptance.

## Shared OpenCloud credentials — owner-approved exception

On 9 September 2026 the owner explicitly accepted reusing Baloo's exact
OpenCloud credentials, including write permissions. No new identity or
read-only account is required. The importer only issues GET and PROPFIND;
this is a code guard, not server-enforced least privilege.

Run `node scripts/sync-newjoy-opencloud-secret.mjs` to copy the three existing
keys from baloo/opencloud-baloo to arc-runners/newjoy-website-opencloud.
It prints only a success/mismatch status and verifies exact values in memory.
Repeat after Baloo credential rotation. This is not automatic Secret replication.
Do not print credentials, commit Secrets, restart Baloo, or broaden its access.

## Build storage and polling

The website ARC scale set mounts newjoy-website-build, a 30Gi expandable
longhorn-ssd PVC, at /newjoy-build. Its two replicas retain observations,
accepted project snapshots, media derivatives, and publication state across
ephemeral runner pods. The PVC opts out of Argo pruning. Watch usage; orphan
cache/snapshot pruning is not implemented yet.

The website workflow is enabled by repository variable
NEWJOY_CONTENT_SYNC_ENABLED=true. NEWJOY_SOURCE_PROJECT_KEYS initially selects
the five authored demonstration projects using opaque public keys; it contains
no private folder names. Keep this bounded canary until live acceptance and a
warm no-download run are verified. Clearing it expands polling to all projects
under the configured 2021–2026 year roots.

Scheduled/manual runs poll OpenCloud; push runs build solely from accepted
snapshots. Polling is requested every 15 minutes, with a three-hour *observed*
quiet window. GitHub schedules can be delayed. Fixtures never substitute for
accepted live content. Each poll preserves invalid/unavailable projects'
last accepted state. Detailed errors stay in state/last-poll.json; Actions logs
contain counts including mediaDownloads and mediaBytes.

The owner approved an initial-deployment exception: dispatch site-image.yaml
with `-f initial_import=true`. Never-accepted projects may qualify from the newest
valid source modification time across renders, catalogs, website.yaml, and
baloo.yaml if all are at least three hours old. Missing/future timestamps use
normal observed timing; known fingerprint changes block the shortcut. Catalog
and before/after version checks remain mandatory. The flag defaults off and
cannot accelerate accepted-project updates or rewrite observation timestamps.
For initially recent files, the source-age deadline persists across subsequent
scheduled polls. A changed fingerprint discards that deadline and requires the
normal observed quiet window.

One ARC runner and non-cancelling workflow concurrency serialize the pipeline.
An interrupted poll can leave state/poll.lock. First verify no runner is active;
only then remove that exact lock. Do not delete accepted state or observations.

The live WebDAV adapter has read all five authored website.yaml files and
inventoried their projects. OpenCloud reports directory getcontentlength as
404 inside an otherwise successful multistatus: the adapter allows only that
specific missing collection property, not missing file data or access failures.

First live ARC poll 34357498360 succeeded at 13:32 UTC on 9 September 2026:
5 observed, 0 eligible, 0 failures, 62 metadata requests, 0 media downloads.
The first observations were made about 13:31:46 UTC; initial eligibility is
about 16:31:46 UTC / 19:31:46 Bucharest if sources remain unchanged.
The registry updater's first run 34357502303 also succeeded and retained the
sample image because no live release exists yet. Full acceptance/publication
and the subsequent warm-cache behavior are still pending verification.
Second poll 34359960556 at 13:54 UTC retained nextEligibleAt
2026-09-09T16:31:46.328Z in a replacement runner, again with five observations,
zero failures, and zero media downloads. Observation persistence is verified;
post-import derivative-cache reuse is not yet verified.

## Publication and automatic staging update

Build code/tests, accepted public content, and artifact privacy checks before
publication. Release identity combines Git revision and accepted snapshot IDs:
unchanged polls do not rebuild/re-publish, and failed builds retry.
Images contain only static pages and optimized media, never raw source or tokens.
Every build uses a unique sha-COMMIT-run-NUMBER-ATTEMPT tag plus immutable digest.
A source-head check skips superseded publications.

Website image builds run on homelab. The separate newjoy-staging-update workflow
runs a registry/Git-only task on a GitHub-hosted runner, using this repository's
GITHUB_TOKEN rather than a cross-repository PAT. Every 15 minutes it selects
the newest run/attempt, uses scripts/resolve-container-image.py to verify public
linux/amd64 availability and the digest, and commits only
config/newjoy-website-staging/manifests/deployment.yaml. It never edits production.
Concurrent Git pushes fail safely and retry on the next run; release ordering
prevents an older run replacing a newer one.

The image resolver's --list --tag-pattern REGEX --limit 0 supports discovery of
these non-version tags; normal version resolution is unchanged.

The already deployed sample image stays in place until the first live candidate
passes acceptance/build. Verify the actual first acceptance, warm-cache run,
image publication, and GitOps advancement before claiming end-to-end completion.

## Promotion and runner operations

Production promotion always requires explicit owner approval and copies the
reviewed staging tag@digest unchanged. No rebuild or source fetch occurs.
Public image visibility (including staging content) was explicitly accepted;
Pocket ID gates web access, not registry artifact downloads.

Runner registration uses arc-runners/github-arc-token, scoped to the selected
repositories including newjoy-website. On 9 September a corrected PAT and a
targeted scale-set annotation restored the listener; the shared ARC controller
was not restarted. Website setup-node pin 6ab0fc9 fixed the initial action error.
Workflow 34328923429 published the initial sample image. See
config/actions-runner-controller/README.md for rotation and registration checks.
