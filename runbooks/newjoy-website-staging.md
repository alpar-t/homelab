# Newjoy website staging and source integration

Website source and importer live in private `alpar-t/newjoy-website`; this
repository owns runner infrastructure and eventual GitOps deployment references.
The portal is a separate application; see `newjoy-portal.md` for the existing
Pocket ID authentication pattern, not website release state.

## Initial checks — 9 September 2026, before registration retry

- `newjoy-website-runners` Application is Synced/Healthy, but that is not proof
  of a usable runner. Its scale set has no listener.
- ARC controller logs at 08:08 UTC report HTTP 404 from
  `POST /repos/alpar-t/newjoy-website/actions/runners/registration-token`.
  The homelab and Baloo-export listeners are healthy.
- No `newjoy-website-staging` namespace exists. No website workflow runs were
  returned by GitHub. Production is unchanged.
- No dedicated website OpenCloud Secret was found. `baloo/opencloud-baloo`
  belongs to the existing integration, not the website builder.
- The website visual checkpoint is unfinished. Infrastructure validation must
  not be described as artistic acceptance or production readiness.

## Repository runner access

The owner must include `alpar-t/newjoy-website` in the fine-grained PAT backing
`arc-runners/github-arc-token`, with repository Administration read/write and
Metadata read. Do not copy a workstation PAT into the cluster or widen access to
all repositories as a shortcut. Never print token values.

After access changes, check the ARC controller and listener before dispatching
the website's manual image workflow. ArgoCD health alone missed this failure.
If rotating the credential, follow `config/actions-runner-controller/README.md`.

The token permissions were corrected on 9 September. A targeted annotation on
the Newjoy AutoscalingRunnerSet triggered reconciliation without restarting the
shared controller. Its listener became healthy. The first workflow exposed an
invalid `setup-node` pin; website commit `6ab0fc9` fixes it using the verified
`v6.2.0` commit. Run `34328923429` then passed. The user made the container package
public, and the image resolver verified anonymous amd64 access to its digest.

`apps/newjoy-website-staging.yaml` and `config/newjoy-website-staging/manifests/`
contain the first staging-only deployment. It uses the sample-content image,
not a live OpenCloud import. All routes require Pocket ID through ingress.

## Remaining integration gates

1. Provision a dedicated OpenCloud reader with Viewer access to the intended
   project source, then an expiring App Token. The builder must not reuse the
   organizer's write-capable token. `baloo-opencloud-mcp.md` describes the existing
   identity, sharing, and App Token pattern; do not change Baloo incidentally.
2. Allocate durable accepted-snapshot, observation, and derivative-cache storage.
   Keep raw source and credentials out of public artifacts and workflow output.
3. Run a bounded live canary with the website's actual adapter. Record the first
   observation durably and respect the real three-hour quiet window; old source
   timestamps are not a substitute. Verify unchanged runs download no media.
4. Wire serialized polling and publication only after the manual path works.
   Check every 15 minutes, build only for accepted-content or source-code changes,
   and prevent an older job from publishing after a newer release. Give content
   releases unique identities even when the Git source commit is unchanged.
5. Publish an immutable image and verify anonymous registry access. Resolve its
   tag and amd64 digest with `scripts/resolve-container-image.py` before writing
   any deployable reference. Keep staging-only manifests out of the active
   app-of-apps until their image and authentication prerequisites exist.
6. Provision the staging Pocket ID client and intended reviewers. Protect the
   root prefix, including assets and environment settings. Verify signed-out
   redirects and authenticated `private, no-store` / no-index responses through
   Cloudflare. The shared OIDC helper logs secret responses, so retain the
   staging wrapper's stdout suppression.

Website templates and details are in its `deploy/homelab/` and
`docs/deployment.md`. Automatic updates stop at staging. Production promotion
requires explicit user approval and copies the exact reviewed image digest;
it never rebuilds or fetches fresh OpenCloud material.
