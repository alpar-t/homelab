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
