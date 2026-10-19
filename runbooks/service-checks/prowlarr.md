# Prowlarr safe monitoring baseline

Observe the existing prowlarr container in the single nonterminating arr-stack pod using existing read-only pod RBAC. Require Running, container ready and a running state. Native API health/indexer checks are explicitly deferred.

Coverage that cannot be obtained with native enforced read-only authority stays
visible as advisory records with severity1, `observation: deferred`, `notification: dashboard` and a `coverage deferred`
detail. These records must not be mistaken for completed functional validation.
The ordinary operational checks use the shared framework's normal severity and
transient grace. Existing Kubernetes/native signals continue independently.

## Access and credential boundary

No anonymous functional API has been verified for this deployed version as part of this change, and no application-wide administrative API key is copied. This is explicitly Kubernetes readiness evidence, not indexer search, active block or upstream availability validation.

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

Run `python3 -m unittest discover -s scripts/tests -p test_service_prowlarr.py`
and `kubectl kustomize config/zabbix/manifests`. Fixtures cover normal operational
evidence, explicit deferred records, rejected/malformed/unavailable evidence,
redaction, deadline expiry and ignored legacy credential config. No production
request or deployment is performed by these tests. Validate actual anonymous
contracts/readiness after the normal reviewed GitOps rollout; this change does
not claim new live functional validation.
