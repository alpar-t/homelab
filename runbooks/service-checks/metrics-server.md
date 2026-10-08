# Kubernetes resource metrics functional check

`Metrics-server fresh node coverage` reads the Kubernetes NodeList and
metrics.k8s.io/v1beta1 NodeMetricsList every five minutes. It rejects empty,
incomplete/paginated, duplicate, unknown-node, or malformed responses. Each
sample must contain CPU/memory quantities, a positive seconds window of at
most 180 seconds, and a timezone-aware timestamp no older than 180 seconds
and no more than 15 seconds in the future.

All inventoried nodes need samples after a five-minute grace measured from
node creation or the Ready condition's last transition (including a restart
or readiness recovery). Existing samples must still be valid during grace;
an entirely empty metrics API never passes. Old NotReady nodes remain expected;
the existing infrastructure checks explain node outages separately. No node
names, usage values or API response bodies enter evidence.

The check uses the existing collector ServiceAccount's node and metrics-node
get/list permissions through the Kubernetes API. No credentials, RBAC,
NetworkPolicy, metrics-server deployment changes or rollout prerequisites
are required beyond the functional-check foundation. Two requests have the
existing client's 15-second timeout, with 15 seconds of budget required before
starting each; the foundation rejects results beyond the 30-second deadline.
Lists are limited to 100 and continuation fails visibly rather than looping.

The foundation retries failures after 60 seconds and retains Zabbix's existing
three-sample trigger. Missing/stale samples usually indicate metrics-server's
kubelet scraping or aggregated API failure; future timestamps indicate clock
skew. First compare `kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes`
with node Ready transitions and inspect metrics-server logs. This is passive
node-metrics coverage: it does not validate pod metrics or numeric resource
accuracy and does not duplicate existing CPU/memory pressure alerts.
