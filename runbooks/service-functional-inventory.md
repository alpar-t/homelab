# Functional monitoring inventory

Inventory taken from live Deployments, StatefulSets, DaemonSets, Services, CronJobs, Ingresses and ArgoCD Applications on 2026-10-08, cross-checked against repository manifests. Home Assistant is a separate appliance. Multiple instances and tightly coupled dependencies are grouped under their operational service.

Each service is assigned an isolated Sol implementation agent and PR. Keep the first baseline small: semantic API reads, protocol transactions or small in-memory conversions; use passive reconciliation evidence for controllers where a synthetic transaction would be disruptive. The common runner executes bounded deterministic checks without invoking an LLM. The existing Zabbix three-failure trigger applies.

PRs target the shared framework branch `feat/monitoring-functional-foundation` until that foundation is merged. Service PRs must then be retargeted to `main`; they are not deployed by this implementation task. Credential and network prerequisites are documented in each PR and service runbook.

| Service | Initial baseline scope |
| --- | --- |
| Actual Budget and its MCP adapter | Verify budget server API semantics/version and authenticated read-only budget listing or sync capability using a deliberately scoped monitor account if supported. Cover MCP transport/catalog without budget mutations or financial-data output. Sources config/actual-budget; avoid downloading actual budgets. |
| ArgoCD GitOps reconciliation | Detect degraded/failed/stalled application reconciliation and repository/comparison failures from Application CRs using narrow read RBAC. Respect intentionally OutOfSync in-progress changes with grace, suspended automation and maintenance. Preserve private admin access; no public endpoint or admin token. |
| Baloo OpenClaw and shared MCP tool integrations | Deterministic gateway/channel integration readiness and relevant MCP handshake/catalog health without LLM calls or WhatsApp sends. Include loopback-only integrations using an appropriately scoped existing health aggregation or exporter, not exposed credentials; inspect native watchdog to avoid duplicate alerts. Account for newjoy-organizer/image-tools/image-api/court/OLX/tools sidecars, mcp-k8s. Document any behavior that cannot be proven safely. Source sibling baloo read-only; prefer homelab-only PR. |
| PinchTab browser services | Both dedicated general-web and OLX PinchTab instances. Verify authenticated browser/session API semantics and browser availability without navigating logged-in tabs or affecting persisted sessions. Honor network isolation, dedicated tokens; no built-in browser or LLM invocation. Read baloo-general-browser runbook. |
| SearXNG search and MCP adapter | A small fixed harmless search with JSON results validates actual query execution; avoid brittle exact result or every-engine requirements. Detect total engine failure/invalid response; optional MCP protocol catalog probe. Read searxng-maintenance runbook and network policies. Slow cadence to avoid upstream load. |
| Whisper speech transcription | Verify Wyoming protocol describe/capabilities reaches loaded speech model and HTTP bridge is usable; consider tiny synthetic fixed audio only if cheap and reliable, no stored speech. Distinguish GPU/model/bridge errors; no LLM calls. Sources config/baloo/manifests/whisper.yaml. |
| Product-model API and Blender renderer | Check API contract, renderer availability and queue/worker progress with bounded grace that accounts for idle and long legitimate jobs. No renders, paid image generation, or user job mutations. Read product-model runbook and deployed API source to choose meaningful readiness beyond process up. |
| Technical-plan generation API | Verify deterministic API/schema/dependencies and a tiny read-only or in-memory validation operation if supported. No production artifact creation or Blender job submission. Sources config and sibling baloo API code. Report useful unavailable/version mismatch signals. |
| Interior Designer Open WebUI | Verify backend API config/version and model/provider integration metadata only if safely read-only, plus frontend entrypoint assets. No model completions, uploads or messages. Distinguish login-only reachability from available application capabilities. Include progress-filter integration if safely observable. |
| Cloudflare Tunnel | Validate connector tunnel connections from its native metrics and one representative public application response with semantic marker, not just pod up. Cover each intended replica when meaningful; avoid duplicate outage storms and heavy requests. Read cloudflare-tunnel-availability runbook; distinguish inside-out check limits. |
| Frigate camera recording | Read Frigate stats to validate configured/enabled cameras have fresh nonzero capture/process frames and no stuck ffmpeg; camera disable/idle detection must not false-alert. Capture/recording health baseline with grace, no snapshots or private footage. Read quarantined HDD runbook; do not alert on intentional exclusions. |
| Immich photos and ML dependencies | Validate server-info/config semantic API plus scoped read-only library/statistics API where supported. Include meaningful ML/Redis dependency or job failure signal without uploads, rescans, downloads or private photo data in output. Verify actual deployed Immich endpoints. |
| Ingress routing | A deterministic internal ingress Host-header request to a known public backend asserts correct routing and semantic body, plus relevant config reload/controller signal if cheap. Avoid counting auth/login redirect as backend success. Preserve public exposure policies; no production ingress mutations. |
| Newjoy public website | Check public and internal homepage semantic marker and one referenced first-party JS/CSS asset successfully served with correct content type/nonempty content. Avoid third-party assets and brittle layout text; catch broken build/deployment SPA fallback. Source landing-page and portal runbooks as relevant. |
| Newjoy website staging | Validate internal staging homepage plus referenced asset; separately verify public Pocket ID protection redirect/status identity without logging in. Respect intentional paused/empty staging if documented; no build trigger or publishing. Read newjoy-website-staging runbook. |
| Longhorn storage service | Existing checks already cover volume health and backup freshness. Add a modest functional/control-plane signal such as API schema/backup-store/controller reconciliation errors, not duplicate generic readiness. No volume mutations or risky synthetic mounts; read runbooks and honor excluded backup groups. Document passive coverage limits. |
| Radarr movies | Authenticated read-only system/health and root-folder/download-client connectivity status via actual Radarr API, using dedicated least-privilege credential where supported. Healthy empty library okay. No search/download/scan or movie changes. Read baloo-radarr-movies runbook; redact paths/titles/details. |
| Sonarr TV | Authenticated read-only API system/health and root-folder/download-client issues. Empty library is okay. No search, scan, download or modifications. Verify API version from deployed source/official docs. Redact titles and filesystem paths. |
| Prowlarr indexers | Read-only API health and configured indexer status signal without invoking indexer tests/searches or excessive upstream load. Honor disabled indexers and don't fail legitimate empty state. Avoid exposing indexer URLs/API keys. |
| qBittorrent downloads | Read-only Web API version/preferences/session and transfer connectivity/queue health using safe scope. Idle/zero torrents must pass; no adding torrents, resume, recheck or deletes. Diagnose auth/API breakage, stalled global offline conditions conservatively. Protect cookies/tokens. |
| Emby media playback service | Semantic server/public info plus read-only library/system query using scoped account if useful. Do not play media or trigger transcoding/library scans. Catch inaccessible library/backend state where cheap, not merely TCP. Healthy empty library can pass. Respect LAN MetalLB routing. |
| Maintainerr media cleanup | Validate service API/database integration and Emby/Sonarr/Radarr integration status through existing read-only endpoints if available. No rules execution, deletes or scheduled cleanup triggers. Idle scheduler normal. Distinguish functional coverage from health-only limitations. |
| MetalLB load balancer | Check expected LoadBalancer service allocations/announcements and representative advertised VIP connectivity using existing service endpoints. Avoid generic pod readiness duplication; handle externalTrafficPolicy Local and intentional pending services carefully. No config changes or packet floods. |
| Node-RED automation runtime | Read-only runtime/admin API or metrics confirms flows loaded and runtime not stopped, plus relevant dependencies if directly observable. No triggering flows or actuators, no exposing flow contents/credentials. Verify configured authentication and Node-RED endpoint semantics. |
| Omada network controller | Verify controller API/login bootstrap semantics and read-only adopted-device connectivity counts with conservative treatment of intentionally offline devices if scoped monitoring is available. No wireless/network changes or login storms. Avoid broad admin credentials just to monitor. |
| OpenCloud files | Verify OCS/WebDAV capability/PROPFIND read-only request against dedicated monitor workspace to exercise storage/auth, plus configured service status semantics. Never list household files into logs or write/delete. Read baloo-opencloud-mcp and recovery runbooks. Coordinate credentials via explicit keys, not admin token. |
| OnlyOffice and OpenCloud collaboration | Check document-server health plus discovery/capabilities schema and collaboration WOPI contract via non-user metadata request. Catch worker/database/conversion dependency failure where supported. No opening real documents or creating office jobs. Sources OpenCloud chart; scope OnlyOffice + WOPI as one editing service. |
| Apache Tika text extraction | Tiny fixed in-memory plain text extraction PUT on both Tika instances (paperless and opencloud), assert expected output/content type. No stored documents. Bound body/time and network ingress. This is a real conversion baseline, not only /version. |
| Gotenberg PDF conversion | Convert tiny fixed local HTML multipart payload into PDF, assert PDF magic and reasonable size. No remote fetches/user docs, low cadence, bounded size/time. Include queue/health signal if useful. Verify actual API. No persistent artifacts. |
| OpenTherm monitor | Read-only runtime data endpoint confirms current boiler/thermostat telemetry freshness and bridge communication. No heating setpoints/commands. Account for idle boiler being normal and legitimate night modes. Inspect app/deployed interface before deciding fields. |
| Paperless documents and ingestion dependencies | Scoped read-only API query validates DB/auth/document listing without returning titles/content; native task/consumer/Redis status if observable. FTP ingress banner/protocol can be included without uploading. Conversion dependencies assigned separately Tika/Gotenberg. No document ingestion/reprocessing or outbound mail. |
| Pi-hole DNS | Real bounded UDP DNS queries against both Pi-hole instances, validate transaction/question/rcode/answer for stable allowed record and locally controlled name if configured. Test TCP fallback as appropriate, no external brittle IP equality. Distinguish per-instance failures. Read pihole redundancy runbook. |
| Pocket ID and application sign-in proxies | Validate OIDC discovery issuer/endpoints and JWKS usable signing keys; representative/all configured oauth2-proxy auth-start responses point to correct issuer/client/callback with sane state, bounded and no actual user login. Existing daily live access-policy check freshness if available. Never create accounts or widen groups. |
| Household portal | Validate portal entrypoint, shipped catalog JSON/required assets and semantic schema, plus public sign-in gate. Admin/family/kids catalogs checked internally without publishing private URLs. No auth bypass or broad cookies. Read newjoy-portal runbook. |
| Roundcube webmail | Verify meaningful login bootstrap/session/form and configured backend IMAP capability rather than only 200; authenticated read-only mailbox session only if dedicated monitor account available. No emails or user mailbox changes. Coordinate with existing Stalwart checks, document login baseline limitations. |
| Stalwart and fetchmail mail delivery | Preserve recent passive incoming activity policy exactly (24/7, initial24h adaptive gaps) and current failure-log checks. Add protocol-level SMTP EHLO/STARTTLS and IMAPS capability/TLS validation for configured local/upstream endpoints where useful. No synthetic emails, no mailbox credentials unless justified, no sending/retrieving message bodies. Existing TCP probes not enough. |
| Tandoor recipes | Read-only API/version/config plus scoped authenticated recipe-list count/schema to prove backend usable without recipe data output. No edits, imports, or meal planning changes. Support empty library. Verify installed API semantics; cheap static asset check if authenticated scope unavailable. |
| TREK trip planner | Validate actual trip-planner API/config/frontend asset contract and read-only trip metadata schema with scoped auth if supported. This is holiday planning, not Star Trek. No changes or personal itinerary data in logs. Inspect app version source/docs. |
| Vaultwarden password vault | Validate Bitwarden-compatible /api/config and identity prelogin protocol with fixed nonexistent monitor identifier, plus web-vault asset contract as useful. No vault downloads/login attempts, password operations, or private usernames. Read compatibility-maintenance runbook and avoid duplicate existing jobs. |
| Vikunja task management | Validate API info/version and scoped authenticated read-only project/task API shape using dedicated account/token or existing safely scoped service account only when justified. No creating/changing tasks or comments. Do not expose task contents. Verify deployed v2 API and relevant adapter contract. |
| Home Assistant appliance | HA is external appliance 192.168.1.102:8123, only recorder DB in k3s. Read-only authenticated /api/config or template runtime freshness health using a dedicated token; select meaningful stable expected entities from local config mirror without actuating. Avoid blanket unknown/unavailable alerts for sleeping devices. No HA deployment/reload or automations changes. |
| Travel WireGuard connectivity | Check meaningful tunnel/listener/config availability and optional expected peer handshake only when configured expected online; travel router offline is normal. No private key reads/printing or host-network privilege expansion. Prefer existing exporter/read-only runtime signal; explain inability to prove remote path from cluster without an active peer. Read travel/wireguard runbooks. |
| Zabbix monitoring pipeline | Complement native Baloo watchdog with actual unauthenticated apiinfo.version JSON-RPC contract and frontend assets/collector freshness or queue health using read-only identity if needed. Do not duplicate periodic LLM checks or send test alerts. Preserve watchdog independent behavior; no bootstrap role mutations. |
| CloudNativePG database platform | Existing cluster readiness and backup/archive freshness checks exist. Add meaningful SQL/backend capability or native metrics such as replication lag/read-write role consistency across expected instances, avoiding broad DB credentials and duplicated readiness. Account for maintenance/grace and healthy empty workloads. Prefer native metrics and narrowly scoped GET access. |
| Velero Kubernetes backups | Validate expected backup schedule completion/freshness and BackupStorageLocation availability from CRs, with clear handling of suspended/no configured schedules and errors. Avoid duplicate Longhorn/CNPG backup checks. Do not start backups/restores. Add narrowly scoped CR read RBAC only. |
| Kubernetes service DNS | Real DNS queries through cluster DNS for kubernetes.default.svc.cluster.local and one stable service, validate expected service IP from Kubernetes API; bounded UDP/TCP, no hardcoded external addresses. This must catch CoreDNS resolver failures despite Ready pods. Separate from Pi-hole upstream checks. |
| Kubernetes resource metrics | Detect stale/missing metrics API timestamps and expected node coverage rather than only existing CPU/memory values. Ensure API JSON shape and timestamp freshness; use existing narrow metrics API access, no broad permissions. Useful missing metrics evidence without alerting on transient startups. |
| GitHub Actions runners and controller | Passive controller/listener/runner registration/reconciliation/queue-age checks across homelab, Newjoy and Baloo export runner sets. Scale-to-zero idle is healthy; no GitHub dispatches or workflow runs. Prefer AutoscalingRunnerSet/EphemeralRunner CR status with narrow read RBAC. No PAT/admin tokens. |
| Cluster support controllers | Inventory remaining support components: local-path provisioner, reloader, system-upgrade, multus/whereabouts, intel GPU plugin, node-config. Existing generic readiness is baseline; add at most a few actionable semantic reconciliation/capacity/allocation failure signals where source proves meaning. Avoid busy synthetic upgrades, PVC allocations, reboots, device use or broad event-log matching. Document components intentionally covered by existing checks versus new functional signals. |

## Live findings and rollout prerequisites

- Pi-hole resolves external names, but the configured local `ha-db.local` record failed on both instances. The check exposes this existing configuration issue; it does not repair DNS.
- Frigate reports zero capture/process frame activity for the enabled back camera. No footage was retrieved and no camera settings were changed.
- Local Stalwart TLS currently uses a self-signed certificate. Its monitoring trust anchor must be provisioned explicitly; hostname verification stays enabled.
- MetalLB's WireGuard `status.node` lagged current speaker metadata. The check uses the current native speaker label and live owner rather than turning the stale field into an outage alarm.
- Authenticated checks require the dedicated credentials/configuration described in their service runbooks. Some native APIs have no read-only token scope; their actual token permissions are explicitly documented. No credentials were provisioned as part of these PRs.
- Whisper's decoder capability route and the product renderer's dependency/activity route require their included application changes and pod rollouts before their checks become healthy.
- No PR was merged or deployed. Live evidence is distinguished from fixture-only validation in each PR; several network paths and authenticated workflows remain rollout checks.

## Scope boundaries

- OAuth sign-in proxies are covered with Pocket ID and their application routes; caches, databases, worker sidecars and MCP adapters are dependencies of their owning service. Tika, Gotenberg, OnlyOffice/WOPI, Whisper and browser services have separate checks because several user workflows depend on them.
- Existing node/storage readiness, resource usage, Longhorn backup health, CNPG archive/backup freshness and mail failure/activity checks remain in place. New service checks must add evidence beyond those signals.
- Internal-to-public requests cover routing and application responses from inside the homelab. They do not replace independent outside-in monitoring of total site/network failure.
- Disabled cameras, idle downloads, stopped travel clients, empty libraries, zero-scale runners and intentionally suspended jobs must not be treated as failures without an explicit expected-state policy.
- No synthetic email sends, model completions, household-data mutations, media downloads, production renders, actuator calls or backup/restore tests are introduced by the baseline.
- Catalog entries and chart templates absent from the live deployment, such as unused OpenCloud optional components, are not treated as running services. Provisioning-only Jobs and retired applications do not get permanent availability alarms.

This inventory records the planned baseline. Per-service runbooks and PR validation sections record what was implemented and the exact evidence/limitations; do not infer complete end-to-end coverage from this table.

## Review index

All 49 service PRs are open. Shared runner: [PR #124](https://github.com/alpar-t/homelab/pull/124). Each service PR records its evidence, limits and rollout prerequisites.

| Service | PR | Runbook |
| --- | --- | --- |
| Actual Budget and its MCP adapter | [#135](https://github.com/alpar-t/homelab/pull/135) | `runbooks/service-checks/actual-budget.md` |
| ArgoCD GitOps reconciliation | [#162](https://github.com/alpar-t/homelab/pull/162) | `runbooks/service-checks/argocd.md` |
| Baloo OpenClaw and shared MCP tool integrations | [#153](https://github.com/alpar-t/homelab/pull/153) | `runbooks/service-checks/baloo.md` |
| PinchTab browser services | [#154](https://github.com/alpar-t/homelab/pull/154) | `runbooks/service-checks/pinchtab.md` |
| SearXNG search and MCP adapter | [#144](https://github.com/alpar-t/homelab/pull/144) | `runbooks/service-checks/searxng.md` |
| Whisper speech transcription | [#156](https://github.com/alpar-t/homelab/pull/156) | `runbooks/service-checks/whisper.md` |
| Product-model API and Blender renderer | [#157](https://github.com/alpar-t/homelab/pull/157) | `runbooks/service-checks/product-models.md` |
| Technical-plan generation API | [#158](https://github.com/alpar-t/homelab/pull/158) | `runbooks/service-checks/technical-plans.md` |
| Interior Designer Open WebUI | [#160](https://github.com/alpar-t/homelab/pull/160) | `runbooks/service-checks/interior-designer.md` |
| Cloudflare Tunnel | [#161](https://github.com/alpar-t/homelab/pull/161) | `runbooks/service-checks/cloudflare-tunnel.md` |
| Frigate camera recording | [#133](https://github.com/alpar-t/homelab/pull/133) | `runbooks/service-checks/frigate.md` |
| Immich photos and ML dependencies | [#129](https://github.com/alpar-t/homelab/pull/129) | `runbooks/service-checks/immich.md` |
| Ingress routing | [#159](https://github.com/alpar-t/homelab/pull/159) | `runbooks/service-checks/ingress-nginx.md` |
| Newjoy public website | [#145](https://github.com/alpar-t/homelab/pull/145) | `runbooks/service-checks/landing-page.md` |
| Newjoy website staging | [#147](https://github.com/alpar-t/homelab/pull/147) | `runbooks/service-checks/website-staging.md` |
| Longhorn storage service | [#164](https://github.com/alpar-t/homelab/pull/164) | `runbooks/service-checks/longhorn.md` |
| Radarr movies | [#140](https://github.com/alpar-t/homelab/pull/140) | `runbooks/service-checks/radarr.md` |
| Sonarr TV | [#138](https://github.com/alpar-t/homelab/pull/138) | `runbooks/service-checks/sonarr.md` |
| Prowlarr indexers | [#139](https://github.com/alpar-t/homelab/pull/139) | `runbooks/service-checks/prowlarr.md` |
| qBittorrent downloads | [#141](https://github.com/alpar-t/homelab/pull/141) | `runbooks/service-checks/qbittorrent.md` |
| Emby media playback service | [#142](https://github.com/alpar-t/homelab/pull/142) | `runbooks/service-checks/emby.md` |
| Maintainerr media cleanup | [#148](https://github.com/alpar-t/homelab/pull/148) | `runbooks/service-checks/maintainerr.md` |
| MetalLB load balancer | [#163](https://github.com/alpar-t/homelab/pull/163) | `runbooks/service-checks/metallb.md` |
| Node-RED automation runtime | [#152](https://github.com/alpar-t/homelab/pull/152) | `runbooks/service-checks/nodered.md` |
| Omada network controller | [#155](https://github.com/alpar-t/homelab/pull/155) | `runbooks/service-checks/omada.md` |
| OpenCloud files | [#131](https://github.com/alpar-t/homelab/pull/131) | `runbooks/service-checks/opencloud.md` |
| OnlyOffice and OpenCloud collaboration | [#149](https://github.com/alpar-t/homelab/pull/149) | `runbooks/service-checks/onlyoffice.md` |
| Apache Tika text extraction | [#146](https://github.com/alpar-t/homelab/pull/146) | `runbooks/service-checks/tika.md` |
| Gotenberg PDF conversion | [#123](https://github.com/alpar-t/homelab/pull/123) | `runbooks/service-checks/gotenberg.md` |
| OpenTherm monitor | [#150](https://github.com/alpar-t/homelab/pull/150) | `runbooks/service-checks/otmonitor.md` |
| Paperless documents and ingestion dependencies | [#128](https://github.com/alpar-t/homelab/pull/128) | `runbooks/service-checks/paperless.md` |
| Pi-hole DNS | [#125](https://github.com/alpar-t/homelab/pull/125) | `runbooks/service-checks/pihole.md` |
| Pocket ID and application sign-in proxies | [#126](https://github.com/alpar-t/homelab/pull/126) | `runbooks/service-checks/pocket-id.md` |
| Household portal | [#143](https://github.com/alpar-t/homelab/pull/143) | `runbooks/service-checks/portal.md` |
| Roundcube webmail | [#137](https://github.com/alpar-t/homelab/pull/137) | `runbooks/service-checks/roundcube.md` |
| Stalwart and fetchmail mail delivery | [#151](https://github.com/alpar-t/homelab/pull/151) | `runbooks/service-checks/stalwart-mail.md` |
| Tandoor recipes | [#134](https://github.com/alpar-t/homelab/pull/134) | `runbooks/service-checks/tandoor.md` |
| TREK trip planner | [#136](https://github.com/alpar-t/homelab/pull/136) | `runbooks/service-checks/trek.md` |
| Vaultwarden password vault | [#130](https://github.com/alpar-t/homelab/pull/130) | `runbooks/service-checks/vaultwarden.md` |
| Vikunja task management | [#127](https://github.com/alpar-t/homelab/pull/127) | `runbooks/service-checks/vikunja.md` |
| Home Assistant appliance | [#132](https://github.com/alpar-t/homelab/pull/132) | `runbooks/service-checks/homeassistant.md` |
| Travel WireGuard connectivity | [#165](https://github.com/alpar-t/homelab/pull/165) | `runbooks/service-checks/wireguard.md` |
| Zabbix monitoring pipeline | [#171](https://github.com/alpar-t/homelab/pull/171) | `runbooks/service-checks/zabbix.md` |
| CloudNativePG database platform | [#168](https://github.com/alpar-t/homelab/pull/168) | `runbooks/service-checks/cnpg.md` |
| Velero Kubernetes backups | [#166](https://github.com/alpar-t/homelab/pull/166) | `runbooks/service-checks/velero.md` |
| Kubernetes service DNS | [#167](https://github.com/alpar-t/homelab/pull/167) | `runbooks/service-checks/coredns.md` |
| Kubernetes resource metrics | [#169](https://github.com/alpar-t/homelab/pull/169) | `runbooks/service-checks/metrics-server.md` |
| GitHub Actions runners and controller | [#170](https://github.com/alpar-t/homelab/pull/170) | `runbooks/service-checks/github-runners.md` |
| Cluster support controllers | [#172](https://github.com/alpar-t/homelab/pull/172) | `runbooks/service-checks/platform-controllers.md` |

## Combined validation

All 49 service changes were assembled with the current foundation in a temporary integration checkout. `scripts/test zabbix access-policy` passed 319 monitoring tests and 11 access-policy tests (330 total). Zabbix Kustomize rendered; all 49 module/config pairs were registered; manifest identities were unique; collector RBAC remained read-only without Secret access. The collector ConfigMap payload is approximately 223 KiB, below its 1 MiB limit. Modified embedded application Python compiled successfully.

Merge the foundation first, then retarget service PRs to `main`. Shared ConfigMap-generator and RBAC additions must be combined as a union when resolving merge conflicts; preserve previously merged services. The integration check validates that combined configuration, not that Git will merge every shared-file edit without conflicts. Provision each service prerequisite before enabling its check.
