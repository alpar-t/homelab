# Pi-hole functional DNS monitoring

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

The Zabbix collector samples both `primary` and `secondary` Pi-hole instances
in namespace `pihole` every 600 seconds, under a 30-second service deadline.
Each has its own stable `Pi-hole <instance> DNS` check in `functional/pihole`.
Normal Zabbix execution-based debounce applies.

The collector discovers pod addresses using its existing read-only pod RBAC,
then sends an A query directly to each address on UDP port 53 for
`cloudflare.com`. A matching transaction ID, question, successful response code,
and matching answer (including CNAME chains) are required. Returned addresses
must be globally routable; no external address is pinned. It also queries the
GitOps-managed `ha-db.local` record over **both UDP and TCP**, requiring
`192.168.1.200` from `config/pihole/manifests/custom-dns-configmap.yaml`.
Truncated UDP responses retry over TCP. Each socket operation is capped at two
seconds and the remaining service deadline; responses and parser work are bounded.

A failure means one instance cannot perform these resolutions, local DNS has
drifted, TCP DNS is broken, or discovery/query execution is unavailable. Check
[Pi-hole redundancy](../pihole-dns-redundancy.md) for diagnosis. Update the
monitor configuration with intentional changes to the controlled local record.
No credentials, new RBAC, or network-policy changes are
needed: Pi-hole currently has no ingress-isolating NetworkPolicy and the
collector has no egress isolation. No HTTP/admin API or user query logs are read.

This exercises each resolver rather than the shared Service, so a working primary
cannot hide a broken standby. It does not prove MetalLB/LAN delivery or failover,
DHCP configuration, every upstream, ad-block list quality, or DNSSEC rejection.
The external query may be answered from cache and depends on the chosen public
name continuing to resolve. No fixed public IP equality is used. DNS queries
have no application mutations and do not simulate outages.

Validation uses protocol fixtures and mocked transport/discovery in
`scripts/tests/test_service_pihole.py`; fixtures alone are not live validation.

## Existing failure found before rollout (2026-10-08)

Transient read-only probes from the existing collector confirmed public
resolution on both instances but failed local resolution on both UDP and TCP.
A subsequent UDP diagnostic returned primary `SERVFAIL` (rcode 2) and secondary
`NXDOMAIN` (rcode 3). The read-only `/api/config/dns/hosts` response on both
instances contains a hosts list but no `ha-db.local` entry. No host contents
were printed and no configuration was changed.

The manifests mounted the v5-style `/etc/pihole/custom.list`, whereas the
[official v6 configuration](https://docs.pi-hole.net/ftldns/configfile/#hosts)
supports `dns.hosts` / `FTLCONF_dns_hosts`. The repair supplies the shared
ConfigMap's host records through that environment setting on both deployments.
Verify the local query over UDP and TCP against each instance after rollout;
the declared-record assertion stays enabled.
