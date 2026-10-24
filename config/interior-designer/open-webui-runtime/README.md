# Patched Open WebUI runtime candidate

The running `ghcr.io/open-webui/open-webui:0.12.3` digest has 23 distinct
critical Trivy IDs. Four are in Pillow 12.3.0 and one is in certifi 2026.7.22.
Pillow 13.0.0 fixes the image parsing issues; certifi 2026.10.23 is newer than
the 2026.10.19 release that removed the compromised emSign trust chain.

This build retains the exact upstream WebUI image, all application files, its
entrypoint and runtime user. It installs only hashed, binary wheels for those
two packages with `--no-deps`, preserving the other installed package metadata.
The upstream 0.12.3 project pins Pillow 12.3.0, so this is an intentional
compatibility override. `pip check` and representative PNG/JPEG image operations
run during the build, but a live no-token startup and actual image upload/edit
probe are required before replacing the production image.

Build manually with `.github/workflows/open-webui-runtime-image.yaml`. Before a
production change, resolve its published linux/amd64 digest with
`scripts/resolve-container-image.py`, scan that exact digest sequentially with
the shared Trivy cache, confirm the before/after count, take a fresh WebUI data
backup, and validate OIDC login, image upload/edit, retrieval and tool-server
paths on the new Pod. Keep the old image pin ready for rollback.
