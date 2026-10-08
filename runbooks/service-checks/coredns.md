# Kubernetes service DNS

Every five minutes, the collector sends four DNS queries directly to the current
kube-dns Service IP: the `kubernetes.default.svc.cluster.local` and
`kube-dns.kube-system.svc.cluster.local` A records over both UDP and TCP port 53.
Each returned address must match its Service's current `spec.clusterIP` from the
Kubernetes API. This catches resolver failures even while CoreDNS pods are Ready.
It does not query Pi-hole or depend on external DNS answers.

Replies require matching transaction ID, question, class/type, successful response
code, no truncation, and the expected owner/address in the answer section.
Compression pointers, frame lengths, response size and record counts are bounded.
Each query has a one-second total budget including TCP connect/send/read. There
are no retries, at most two API reads and four DNS queries per execution.
The existing Kubernetes client has a 15-second API timeout: a read starts only
with 19 seconds remaining, preserving DNS time inside the 30-second deadline.
An unavailable/denied API or exhausted budget reports monitoring failure, never
healthy DNS. The API client's hostname itself relies on cluster DNS; its failure
can prevent the more specific UDP/TCP results, but still surfaces an outage.

No credentials are provisioned. Namespace-local Roles permit only `get` of
`default/kubernetes` and `kube-system/kube-dns` Services for the collector;
no list, Secret access or write permissions are added. Existing DNS network
access is used. Workloads, CoreDNS configuration and upstream resolvers stay as
configured. Failed samples retry at the framework's one-minute interval and
use the existing three-failing-sample Zabbix debounce.

Investigate Service metadata/access when monitoring is unavailable. For protocol
failures inspect CoreDNS logs, endpoints, DNS NetworkPolicies and UDP/TCP routing.
This proves service-name resolution through the DNS Service from the collector;
it does not isolate individual replicas, validate AAAA/headless records, or prove
resolution from every workload/node. No application requests or data changes run.
