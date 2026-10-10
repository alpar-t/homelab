# Home Assistant appliance safe monitoring baseline

Anonymous frontend shell must identify Home Assistant and include its home-assistant application element; /api/ must reject anonymous access with401. Authenticated configuration and energy entities are explicitly deferred.

Coverage that cannot be obtained with native enforced read-only authority stays
visible as advisory records with severity1, `observation: deferred`, `notification: dashboard` and a `coverage deferred`
detail. These records must not be mistaken for completed functional validation.
The ordinary operational checks use the shared framework's normal severity and
transient grace. Existing Kubernetes/native signals continue independently.

## Access and credential boundary

HA native user tokens can actuate entities/services and cannot enforce read-only scope. Never copy a household, administrator or dedicated actuator-capable token into monitoring. Anonymous checks prove frontend delivery and an authentication guard, not recorder writes, integrations, sensor freshness or automation execution. The recorder DB retains its separate Kubernetes/CNPG checks.

No broad native token is an acceptable rollout prerequisite. No proxy is added.
The foundation projects only approved native read-only credential keys and the
public mail TLS CA; legacy unsafe keys are not mounted. If unsafe credentials
were provisioned separately before this change, an authorized operator should
remove/revoke them through the existing private credential workflow; this PR
does not retrieve, provision or rotate any production credential.

## Collection and validation

The shared framework samples at a 10-minute healthy cadence. Operational
failures require two real failed observations and a 15-minute grace;
recovery requires two real healthy observations. Cached snapshots are not new
observations. Failure retries follow the same bounded source-controlled cadence,
with shared jitter and overload limits. Deferred checks remain severity1,
observation deferred and dashboard-only; they never assert functional success.

The JSON interval/deadline policy remains source-controlled and the service uses
bounded requests within that deadline. The shared service deadline remains bounded by its JSON policy. HTTP requests use only fixed
anonymous paths and the shared redirect/TLS/body-limit helper; no response bodies,
credential values or exception strings enter snapshot evidence. Kubernetes reads
use existing read-only RBAC, one bounded inventory page, and refuse pagination.

Run `python3 -m unittest discover -s scripts/tests -p test_service_homeassistant.py`
and `kubectl kustomize config/zabbix/manifests`. Fixtures cover normal operational
evidence, explicit deferred records, rejected/malformed/unavailable evidence,
redaction, deadline expiry and ignored legacy credential config. No production
request or deployment is performed by these tests. Validate actual anonymous
contracts/readiness after the normal reviewed GitOps rollout; this change does
not claim new live functional validation.
