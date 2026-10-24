# SearXNG search

`search.newjoy.ro` uses the existing SearXNG deployment in `baloo`, protected by
Pocket ID and `oauth2-proxy-search`. Allow `family_users`, `kids`, or
`advanced_apps`; keep the policy and portal catalogs aligned as documented in
`pocket-id-access.md`. Baloo uses the internal `searxng` Service directly.

## Google returns no links

On 14 September 2026 the June image returned HTTP 200 and zero Google results
without engine errors, even for `roborock`. Brave was rate-limited and
DuckDuckGo/Startpage returned CAPTCHAs, leaving General empty although Images
and News worked. Isolated `!go roborock` and `!bi roborock` queries distinguished
Google's failure from the shared network path: Google returned zero links and
Bing returned ten.

The verified `2026.9.13-e61d09756` image includes the updated upstream Google
request/parser. A temporary pod with the same settings returned nine Google
links for both `!go roborock` and `!go Kubernetes`, with no engine errors.
Resolve image tags with `scripts/resolve-container-image.py` and test Google
alone before changing deployment defaults. The upstream engine implementation:
https://github.com/searxng/searxng/blob/e61d09756/searx/engines/google.py

After upgrading, verify ordinary General queries and working categories such
as Images and News. Read `/search?q=...&format=json` through the internal Service
and inspect `results` and `unresponsive_engines`. Use `!go` or `!bi` in the query
to isolate an engine; an `engines` parameter alongside categories can still
include default engines. Do not count HTTP 200 as successful search without
checking returned links. Public root, search, and JSON requests must redirect
to Pocket ID when signed out.

## 2026-10-24 CA trust upgrade

The former `2026.9.13-e61d09756@sha256:3f2d2afdb8e455f843ed48d11a0d9f6aeea8de685844ae6695d455b880665ef4`
had one critical finding, [certifi GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2). SearXNG's outbound
`curl_cffi` client actually used `/etc/ssl/certs/ca-certificates.crt` with TLS
verification enabled. Both that active system store and the old certifi bundle
contained emSign ECC Root CA - G3, whose certificate family was removed after a
compromised intermediate key. Upgrading certifi alone would not have changed
the active trust store.

The verified `linux/amd64` replacement is
`docker.io/searxng/searxng:2026.10.24-ef0ec03da@sha256:7c7cbe509429e82755104b2a95f52085a98633c95d53f44e4e905fa3a59f08c8`.
Its exact-digest Trivy scan found zero critical IDs; certifi is 2026.10.19 and
the active system store no longer contains the G3 root. An isolated pod using
the existing settings returned nonempty Bing, General, Images, and News JSON
results. Google reported access denied on both old and new images, so that
engine remains an upstream availability issue.

GitOps commit `010f77a6` rolled out the new image. The production Service
returned nonempty General JSON results, the MCP adapter listed and executed
`searxng_web_search`, and anonymous homepage/JSON requests redirected to the
OAuth sign-in path. The running-image scanner's next inventory mapped the exact
new digest to `baloo/Deployment/searxng/searxng` with zero critical findings.
Retain the former image reference above for a Git rollback.
For later upgrades, verify both the Python package and the CA file actually
used by `curl_cffi`, then repeat the category, MCP, and signed-out access checks.
