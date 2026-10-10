# Product models safe monitoring baseline

One existing read-only Kubernetes Deployment list checks product-model-api and product-model-renderer observed generation, desired replicas and available/ready replicas. Worker contracts, renderer dependencies and render-deadline coverage are explicitly deferred.

Coverage that cannot be obtained with native enforced read-only authority stays
visible as advisory records with severity1, `observation: deferred`, `notification: dashboard` and a `coverage deferred`
detail. These records must not be mistaken for completed functional validation.
The ordinary operational checks use the shared framework's normal severity and
transient grace. Existing Kubernetes/native signals continue independently.

## Access and credential boundary

Both original private NetworkPolicies remain unchanged. No collector ingress to18810/18811, gateway token, queue request, render, download, script or user job is accessed. The unused renderer capabilities route/activity instrumentation has been removed. Renderer POST executes caller-supplied scripts; permitting its port would grant execution authority. Readiness does not prove Blender execution, scratch capacity, worker progress, deadlines, OpenCloud publication or output validation.

No broad native token is an acceptable rollout prerequisite. No proxy is added.
The foundation projects only approved native read-only credential keys and the
public mail TLS CA; legacy unsafe keys are not mounted. If unsafe credentials
were provisioned separately before this change, an authorized operator should
remove/revoke them through the existing private credential workflow; this PR
does not retrieve, provision or rotate any production credential.

## Collection and validation

The shared framework samples at a 15-minute healthy cadence. Operational
failures require two real failed observations and a 30-minute grace;
recovery requires two real healthy observations. Cached snapshots are not new
observations. Failure retries follow the same bounded source-controlled cadence,
with shared jitter and overload limits. Deferred checks remain severity1,
observation deferred and dashboard-only; they never assert functional success.

The JSON interval/deadline policy remains source-controlled and the service uses
bounded requests within that deadline. The shared service deadline remains bounded by its JSON policy. HTTP requests use only fixed
anonymous paths and the shared redirect/TLS/body-limit helper; no response bodies,
credential values or exception strings enter snapshot evidence. Kubernetes reads
use existing read-only RBAC, one bounded inventory page, and refuse pagination.

Run `python3 -m unittest discover -s scripts/tests -p test_service_product_models.py`
and `kubectl kustomize config/zabbix/manifests`. Fixtures cover normal operational
evidence, explicit deferred records, rejected/malformed/unavailable evidence,
redaction, deadline expiry and ignored legacy credential config. No production
request or deployment is performed by these tests. Validate actual anonymous
contracts/readiness after the normal reviewed GitOps rollout; this change does
not claim new live functional validation.
