# Baloo product-model worker

`config/interior-designer/manifests/product-model-api.yaml` runs one
Blender-backed API pod in `baloo`, placed on `pamacs` through its
`workload/cpu-intensive=true` label. The pod has no Kubernetes service-account
token or job-creation RBAC. It uses a Longhorn SSD PVC for a SQLite queue,
allows one active Blender subprocess and three waiting requests, and enforces
a 15-minute default child-process deadline plus a 2 CPU / 4 GiB pod limit.
The pod can restart without discarding queued requests. An active request is
retried once after a restart, then failed to avoid repeating an OOM crash.
Recreate deployment
strategy prevents a normal rolling update from running two queue owners.

The API and builder are loaded from the private Baloo repository by git-sync:
`openclaw/tools/product-model-api.py` and `product-model-blender.py`. Merge
and verify that Baloo source before promoting this Homelab manifest. The API
uses the existing `baloo-secrets` gateway token to authenticate the narrow MCP
adapter, and `opencloud-baloo` WebDAV credentials to write only generated
paths under the shared Newjoy root's `3D Warehouse/` folder. The folder is
created on the first successful build. The model GLB is uploaded and verified
before the adjacent JSON manifest is published.

The agent-facing tools are `product-models__create_product_model` and
`product-models__wait_for_product_model`. Submit a linked product from Baloo
Open WebUI, follow the job until completion, and verify that both returned
OpenCloud browser links open for the signed-in user. Download the GLB and
import it through SketchUp 2026's File > Import. Check dimensions, orientation,
material appearance, and whether the embedded textures appear. Inspect the
manifest's `localizations.ro`, `.hu`, `.en` and `balooExport` mapping. A plain
GLB import is only a geometry check; the future `baloo_export` warehouse
importer will apply the manifest's type, tag, URL, and notes to the imported
component.

For operations, inspect `kubectl -n baloo get pods -l
app.kubernetes.io/name=product-model-api`, `kubectl -n baloo logs
deployment/product-model-api -c product-model-api`, and `kubectl -n baloo top
pod -l app.kubernetes.io/name=product-model-api`. The authenticated job-status
endpoint reports queued, running, completed, or failed. A 429 response means
the four-request capacity is full. Failed jobs retain a concise error in the
queue; completed artifacts remain in OpenCloud. Do not manually delete queue
files while the pod is running.
