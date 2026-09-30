# Baloo product-model worker

The controller in `config/interior-designer/manifests/product-model-api.yaml`
owns the bounded queue, public HTTPS product-image download, output validation,
and authenticated OpenCloud publishing. Its PVC holds SQLite queue state and
temporary controller files; Blender does not mount it.
It has the gateway and WebDAV credentials, but no Kubernetes service-account
token. It never executes generated Blender code.

`config/interior-designer/manifests/product-model-renderer.yaml` runs a
permanently ready Blender HTTP service. It accepts only requests from the
controller pod on port 18811. Its NetworkPolicy denies all egress, including
DNS and cluster services. The renderer has no service-account token, secrets,
Git checkout, or PVC; it uses bounded emptyDir scratch space and a read-only
ConfigMap for its HTTP handler. Each accepted request runs one Blender child
with a 15-minute deadline and 2 CPU / 4 GiB pod limits. The service returns
only a GLB, bounds metrics, and four preview PNGs in a bounded ZIP response.

The modeler inspects a linked product, generates a scene-construction script,
reviews the full script for non-modeling code, and calls
`product-models__review_product_model_script`. The controller repeats the
deterministic AST screen and requires the exact review SHA-256 before queueing.
This screen is not a Python sandbox; the renderer pod's lack of credentials,
persistent mounts, and egress is the security boundary. The controller sends
the archived reference image and trusted export wrapper to the renderer. The
renderer imports its exported GLB before making material previews, so the
modeler reviews the actual deliverable. The controller checks declared bounds
and GLB structure. It publishes immutable model, source image,
source script, four previews, and manifest paths under `3D Warehouse/` only
after output verification. A failed revision retains the previous files.

The API and wrappers are loaded from Baloo via git-sync. Merge and verify the
Baloo source before promoting this Homelab manifest. The outer API gets its
renderer URL from `PRODUCT_MODEL_RUNNER_URL`; the renderer has no Baloo
repository credentials. Submit and review a test product from Open WebUI, wait
for completion, inspect all four preview images and the GLB in SketchUp 2026,
and verify the source-script and manifest browser links. A plain GLB import
does not apply the manifest's Baloo Export attributes.

For operations, inspect `kubectl -n baloo get pods -l
app.kubernetes.io/name=product-model-api`, the matching renderer pod and
`kubectl -n baloo get networkpolicy product-model-renderer-isolation`.
The authenticated job-status endpoint reports queued, running, completed, or
failed. A 429 response means queue capacity or renderer capacity is full.
Failed jobs retain a concise error in SQLite; completed artifacts remain in
OpenCloud. Do not manually delete queue files while the API pod is running.
