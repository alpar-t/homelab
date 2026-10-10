# Kubernetes resource metrics functional check

## Polling and incident confirmation

Poll every 600 seconds (10 minutes); shared failure grace is 900 seconds.
A problem needs both the elapsed grace and at least two independent failed
executions; recovery needs two independent healthy executions. At this cadence
and grace, ordinary continuous failure normally requires three failed runs.
Minute snapshots never count as new observations, and failures keep the same
slow cadence. Scheduling is staggered. Referenced workload reboot/rescheduling
grace and maintenance preserve confirmed state without declaring recovery.
Persistent ordinary outages page; module-specific advisories stay on the dashboard.
See [the shared framework](../service-functional-checks.md) for startup,
unknown/deferred observations and queue freshness.

`Metrics-server fresh node coverage` reads the Kubernetes NodeList and
metrics.k8s.io/v1beta1 NodeMetricsList every ten minutes. It rejects empty,
incomplete/paginated, duplicate, unknown-node, or malformed responses. Each
required sample must contain CPU/memory quantities, a positive seconds window of at
most 180 seconds, and a timezone-aware timestamp no older than 180 seconds
and no more than 15 seconds in the future.

Only Ready nodes beyond a five-minute grace need current samples. Grace is
measured from node creation or the Ready condition's last transition. Missing
or stale samples from known NotReady/Unknown nodes do not create a duplicate
metrics-server incident; evidence exposes the excluded node count. Existing
samples still require valid identity, timestamp, window and usage shapes, and
duplicate/unknown nodes or truncated lists fail. If no Ready node is beyond
startup grace, the observation is unknown rather than a confirmed recovery.
No node names, usage values or API response bodies enter evidence.

The check uses the existing collector ServiceAccount's node and metrics-node
get/list permissions through the Kubernetes API. No credentials, RBAC,
NetworkPolicy, metrics-server deployment changes or rollout prerequisites
are required beyond the functional-check foundation. Two requests have the
existing client's five-second timeout, with five seconds of budget required before
starting each; the foundation rejects results beyond the 30-second deadline.
Lists are limited to 100 and continuation fails visibly rather than looping.

The foundation keeps the same slow cadence and confirms distinct executions. Missing/stale samples usually indicate metrics-server's
kubelet scraping or aggregated API failure; future timestamps indicate clock
skew. First compare `kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes`
with node Ready transitions and inspect metrics-server logs. This is passive
node-metrics coverage: it does not validate pod metrics or numeric resource
accuracy and does not duplicate existing CPU/memory pressure alerts.
