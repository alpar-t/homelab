# Newjoy public website functional checks

`service_landing_page` runs every five minutes with a 30-second worker deadline.
Two checks fetch the internal landing-page Service and public HTTPS `newjoy.ro`
route. Each requires HTTP 200, HTML content type, document/head/body/title/h1
structure, and `newjoy.ro` identity in title or heading. It accepts the current
inline CSS without relying on marketing copy or layout classes.

If the homepage declares same-origin JS or CSS, the first such asset is fetched
and must be nonempty with a matching content type. HTML SPA fallback fails.
Third-party assets are never fetched. Current source declares no first-party
JS/CSS files, so inline stylesheet syntax is the styling baseline. Cloudflare
may rewrite public fonts into inline CSS; font files are outside this baseline.
Requests cap homepage at 256 KiB and the selected asset at 512 KiB, each with
at most six seconds and remaining worker time. Redirects fail visibly.

No credentials, new RBAC, or access policy changes are needed. Landing-page has
no ingress NetworkPolicy and collector has no egress isolation in source.
Deploy only after foundation PR #124; normal three-failing-sample debounce applies.

A failure means the homepage contract, delivery route, or selected frontend
asset is unavailable. Inspect landing-page ConfigMap/Service/Ingress and public
Cloudflare delivery before changing expectations. Keep identity aligned when
replacing the placeholder site. This does not execute JavaScript, render pixels,
check all replicas/assets, follow outbound links, or prove availability from an
external internet location. It performs at most four GETs per five-minute run.

Implementation evidence: public curl retrieved the expected placeholder HTML on
2026-10-08; this workstation's Python HTTP client received 403 text/plain.
Verify the collector's public route at rollout and adjust a narrowly scoped
Cloudflare monitoring policy if it is denied. No Cloudflare policy was changed.
Internal live delivery was not exercised from this workstation.
