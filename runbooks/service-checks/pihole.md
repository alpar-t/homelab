# Pi-hole functional DNS monitoring

The Zabbix collector samples both `primary` and `secondary` Pi-hole instances
in namespace `pihole` every 300 seconds, under a 30-second service deadline.
Each has its own stable `Pi-hole <instance> DNS` check in `functional/pihole`.
Normal Zabbix three-failure debounce applies.

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
No credentials, new RBAC, network-policy changes, or rollout prerequisites are
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
