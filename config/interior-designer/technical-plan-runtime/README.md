# Technical plan runtime image

The technical plan API and renderer are Baloo scripts mounted by git-sync.
Their PEP 723 metadata declares Python dependencies; both containers must run
their scripts through `uv run --script`. This image supplies Python, uv, Cairo,
and a font without carrying Open WebUI's unrelated packages.

The workflow publishes `ghcr.io/alpar-t/technical-plan-runtime:sha-<commit>`
but does not update the Deployment. A new GHCR package is private by default.
Before pinning it in `technical-plan-api.yaml`, make the package public or
provide a cluster pull credential, then prove an unauthenticated registry read
with `skopeo inspect --no-creds docker://<tag>`. The Baloo pods have no image
pull secret. Public GHCR packages allow anonymous pulls; changing visibility
to public cannot be reversed.

Resolve the published tag with `scripts/resolve-container-image.py`, scan its
exact digest with the procedure in `runbooks/vulnerability-scanning.md`, and
pin the returned `reference=` in both `prepare-renderer` and
`technical-plan-api`. Check startup of both containers and run a real
technical plan preview through the existing authenticated workflow before
retiring the old Open WebUI image. The Dockerfile build checks CairoSVG PDF and
PNG rendering; it does not exercise Baloo's mounted scripts or OpenCloud.
