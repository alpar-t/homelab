# Newjoy website staging functional checks

Every five minutes, the Zabbix functional collector checks the internal homepage
for the New Joy identity and staging UI marker, then fetches one declared
first-party Astro stylesheet. Missing assets, HTML fallback responses, broken
content types and an unrelated login/error page fail this check. It separately
validates environment.json identifies staging with the preview banner enabled.
The live homepage contract was inspected read-only on 8 October 2026.

The public signed-out root must redirect to staging.newjoy.ro/oauth2/start with
the expected return URL. That endpoint must redirect to auth.newjoy.ro/authorize
with a code flow, client ID, state, openid scope and the staging callback. No
redirect is followed to Pocket ID and no credentials or cookies are supplied.
An accidentally exposed homepage, wrong callback/issuer, or failed proxy fails.
This verifies sign-in routing, not completed authentication, group authorization,
visual design or importer/build/publication functionality.

Requests use HomePBP-monitor/1, five-second timeouts, a 256KiB response cap and
the shared 30-second execution deadline. Results contain only fixed diagnostic
messages. Existing three-failure alert debounce applies. No credentials, new
RBAC or destination ingress permissions are required: staging has no restricting
NetworkPolicy and the collector permits HTTP/HTTPS egress.

Keep the last accepted/sample staging image monitored while source polling or
publication is idle. No publication-age or story-count expectation is imposed;
an empty project catalog is valid. The source Deployment currently intends one
replica. If staging is deliberately retired or paused, remove this module/config
from the collector generator as part of that reviewed source change rather than
silently considering an unavailable endpoint healthy. See
[newjoy-website-staging.md](../newjoy-website-staging.md) for rollout operations.
