# Pocket ID functional checks

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

Every 10 minutes, within a 25-second service deadline, the collector fetches
internal OIDC discovery and JWKS metadata. It requires the configured public
issuer, authorization/token/JWKS endpoints, authorization-code and openid
support, and at least one public RSA RS256 verification key with a key ID,
2048-bit modulus and usable exponent. This catches broken metadata, invalid
signing-key publication and incompatible signing changes despite healthy pods.

The portal and search oauth2-proxy instances represent the shared provisioner
and group-aware sign-in configuration. A GET to `/oauth2/start` must return a
302 to the configured Pocket ID authorization endpoint, with the exact client
ID and callback, code flow, openid/groups scope, bounded nonempty state and a
secure HttpOnly CSRF cookie. Responses and cookies are discarded; no redirect
is followed and no account, session or user login is created. A generated
anonymous CSRF cookie is not a successful authenticated session.

No credentials, Kubernetes RBAC additions or network policy changes are needed:
these internal Services have no matching ingress isolation policy, and the
collector has unrestricted egress. Requests cap bodies at 64 KiB and timeouts
at five seconds (also constrained by remaining deadline). Evidence contains
only fixed descriptions, never cookies, redirect query values or key material.
Existing execution-based debounce applies.

Read-only checks from the existing OpenClaw pod confirmed the deployed discovery
contract, RSA RS256 key shape and both redirect/client/callback/CSRF contracts.
This is not evidence of connectivity from a deployed collector running this
module. The public discovery request from the workstation returned 403.

This baseline does not prove passkey login, token issuance/signature verification,
group enforcement, callback redemption, session refresh, public ingress or every
proxy. It neither invokes nor replaces the daily Pocket ID client-group audit;
the daily audit execution freshness is outside this baseline (no additional
CronJob RBAC is granted).
Continue repository access-policy tests and the documented live policy audit
for authorization assurance. No admin API credential is copied into monitoring.
If issuer URLs, signing algorithms or representative clients deliberately
change, update this source-controlled contract alongside the deployment.
