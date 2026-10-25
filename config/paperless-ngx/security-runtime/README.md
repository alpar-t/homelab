# Paperless 3.3.4 Brotli security candidate

The upstream 3.3.4 image includes PyPI Brotli 1.2.0. Its decoder is affected by
[GHSA-9v8h-qqgm-4m35](https://github.com/advisories/GHSA-9v8h-qqgm-4m35).
This derivative pins the verified upstream Linux amd64 digest and replaces only
the Python Brotli wheel with the fixed 1.2.1 release. The wheel hash is from
[PyPI's release metadata](https://pypi.org/pypi/Brotli/1.2.1/json).

The Docker build checks package consistency and exercises Brotli response
compression and HTTPX response decoding. Before use, resolve the published tag
with `scripts/resolve-container-image.py`, scan the exact digest sequentially
using the shared Trivy cache, then test Paperless startup, authentication,
document ingestion and export on the candidate. The production Deployment is
deliberately separate from this build-only candidate.
