# Home Assistant functional baseline

The external HA OS appliance is `192.168.1.102:8123`; the Kubernetes HA
namespace only contains its recorder database. This check never reloads HA,
changes automations, or invokes services.

Every five minutes, the collector performs four authenticated GETs:

- `/api/config`: require a nonempty version and loaded api, recorder and
  automation components. This catches authentication/API failures and missing
  core integrations, but does not prove recorder SQL writes or automation execution.
- `/api/states/<entity>` for the three `sensor.victron_system_grid_l[123]`
  entities used by `config/homeassistant/ha/packages/victron.yaml`: require the
  requested identity and a finite numeric state. Zero and negative power are normal.

Requests use five-second timeouts, bounded responses and the foundation's
30-second execution deadline. Existing three-failure debounce applies. Output
contains counts only, never sensor values, locations, response bodies or tokens.
Missing credentials fail both checks rather than silently disabling coverage.

## Credential prerequisite

Create a dedicated Home Assistant local user named `zabbix-monitor`, with
administrator access disabled. Sign in as that user, open its profile and create
a long-lived access token named `Zabbix functional monitor`. HA long-lived tokens
inherit user permissions; they are not HTTP-method or entity scoped. A regular
HA user can still control entities. HA does not provide a built-in read-only
REST token: this implementation uses only GETs, but the credential itself must
be protected as an actuator-capable credential. Do not reuse a household/admin
or MCP token. If policy requires enforced read-only credentials, do not provision
this token until an independently restricted API proxy is available.

Place the token in a local protected file, then add its contents under the key
`homeassistant_monitor_token` to the manually managed
`zabbix/zabbix-functional-credentials` Secret. Preserve all other service keys;
never replace the shared Secret with a single-key manifest. The foundation
mounts it under `/credentials/`; no Secret API read RBAC is added. Delete the
long-lived token in the dedicated user's profile to revoke it; replace only
this key after rotation. This source change does not provision a user or Secret.

The collector must be able to reach the appliance on LAN TCP/8123. Its namespace
has no egress restriction, and HA is outside Kubernetes, so no destination pod
NetworkPolicy changes are needed. HTTP follows the existing private LAN endpoint;
the bearer token traverses that LAN in cleartext.

## Limits and response

Check the token/user and appliance API after configuration failures. After energy
entity failures, check the continuously powered Victron integration and entity
IDs before changing the expected list. Sleeping phones, battery sensors, pool
seasonal devices and all other entities are deliberately outside this baseline.
Do not check age of `last_changed` or `last_updated`: an unchanged valid reading
can legitimately retain an old timestamp. Consequently, silently frozen numeric
states are not detected. Configuration availability does not prove runtime
freshness, automation firing, recorder persistence, or actuator health.

REST endpoint and bearer-token contracts: [official HA REST API documentation](https://developers.home-assistant.io/docs/api/rest/).
