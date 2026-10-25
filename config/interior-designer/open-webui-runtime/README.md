# Patched Open WebUI runtime candidate

The running `ghcr.io/open-webui/open-webui:0.12.3` digest has 23 distinct
critical Trivy IDs. Four are in Pillow 12.3.0 and one is in certifi 2026.7.22.
Pillow 13.0.0 fixes the image parsing issues; certifi 2026.10.23 is newer than
the 2026.10.19 release that removed the compromised emSign trust chain.

This build retains the exact upstream WebUI image, all application files, its
entrypoint and runtime user. It installs only hashed, binary wheels for Pillow,
certifi, Brotli and brotlicffi with `--no-deps`, preserving the other installed
package metadata. Brotli and brotlicffi 1.2.1/1.2.1.0 address
GHSA-9v8h-qqgm-4m35 in upstream HTTP response decoding.
The upstream 0.12.3 project pins older versions of all four packages, so these
are intentional compatibility overrides. `pip check`, Brotli decoder roundtrips
and representative PNG/JPEG image operations run during the build, but a live
no-token startup and actual image upload/edit and upstream HTTP Brotli probes
are required before replacing the production image.

Build manually with `.github/workflows/open-webui-runtime-image.yaml`. Before a
production change, resolve its published linux/amd64 digest with
`scripts/resolve-container-image.py`, scan that exact digest sequentially with
the shared Trivy cache, confirm the before/after count, take a fresh WebUI data
backup, and validate OIDC login, image upload/edit, retrieval and tool-server
paths on the new Pod. Keep the old image pin ready for rollback.
