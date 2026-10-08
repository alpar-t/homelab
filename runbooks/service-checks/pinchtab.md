# PinchTab functional monitoring

The collector checks both dedicated PinchTab services every five minutes,
with a 30-second total deadline, four-second requests and 128 KiB response caps.
Three failed collector observations use the existing Zabbix debounce. Stable
checks are `PinchTab general web` and `PinchTab OLX` in `functional/pinchtab`.

Bearer-authenticated `GET /health` must report the dashboard contract, `ok`,
enabled authentication, a nonempty version, instance count and restart flag.
`GET /instances` must return valid instance metadata; `error` instances or a
pending configuration restart fail. The general-web service additionally reads
`GET /sessions`, validating the session registry contract. OLX intentionally
does not enable agent sessions. Bearer requests do not touch agent session
activity, extend expiry, create sessions or prune the store. Empty registries,
stopped instances and normal starting/stopping transitions are healthy.

## Credential prerequisite

PinchTab 0.15.1 supports one server bearer token, **not a read-only monitoring
token**. Agent Session tokens can authorize browsing and touch activity on
authentication; they are unsuitable here. Separate Secret key names do not
reduce the privileges of a native bearer token. The collector can therefore
control browsers if compromised. Decide explicitly whether to accept this
before rollout; this PR does not provision or copy existing tokens.

After accepting that limitation, manually populate `pinchtab_web_token` and
`pinchtab_olx_token` in the existing
`zabbix/zabbix-functional-credentials` Secret using protected files and your
normal Secret-management procedure. They must match the respective
`baloo/pinchtab-web-baloo` and `baloo/pinchtab-baloo` `token` values. Preserve
other credential keys when updating the shared Secret. Never use a token on
the command line, print it or commit it. The collector only reads mounted files;
it gets no Secret API permission. Missing keys fail as unavailable. Revoke
monitoring access by removing these two keys and the narrow policy ingress rules;
rotate each native service token and its Baloo consumers if disclosure occurs.

Ingress permits only pods with `app: collector` in namespace `zabbix`, on TCP
9867. The existing OpenClaw ingress and public-web-only egress remain intact.
The two services retain separate tokens, profiles and policies. There is no
generic browser-tool access, LLM invocation or new Kubernetes RBAC.

## Coverage and diagnosis

Failures catch token rejection, malformed API responses, transport timeouts,
reported instance errors and unapplied configuration restarts. Inspect the
service logs and `runbooks/baloo-general-browser.md`; monitoring output contains
no session IDs, agent names, profiles, pages, error payloads or tokens.

This is a passive browser-availability signal from the native instance registry,
not proof of Chromium/CDP responsiveness, navigation, login freshness or website
availability. An idle OLX service normally has no instances. No request starts a
browser, navigates a tab, reads page data, screenshots or cookies, or changes
persisted sessions. Do not use the child instance `/health` to strengthen this
check: bridge health can lazily initialize a browser. Native dashboard health
only reads control-plane metadata. Requests are fixed source-controlled paths;
redirects are refused.

API semantics were checked against upstream tag `v0.15.1` at commit
`a61e86802da0ef5ded2b27b9c8c46d5999999f67`: dashboard `config_health.go`,
`agent_session_api.go`, session `Store.List`, orchestrator `instance_query.go`
and auth middleware. Read-only live checks from the existing OpenClaw
config-renderer verified both health and instance schemas and general-web
session listing. They returned `ok`, authenticated dashboard metadata, one
running general-web instance and an idle OLX registry. Existing tokens were used
only inside their authorized container for verification and were not copied.
