# Service functional checks

Add `config/zabbix/manifests/assets/service_<slug>.py` and adjacent
`service_<slug>.json`; slug uses lowercase letters, digits and underscores.
Add both files to the collector ConfigMap's `files` in `kustomization.yaml`.
There is no service registry. Each module exports `run(ctx, config)` returning
 a nonempty list of dictionaries:

```python
def run(ctx, config):
    response = ctx.http(config['url'])
    return [ctx.check('Example catalog read', response.status != 200,
                      f'HTTP {response.status}')]
```

Each record contains stable unique `name` (up to 160 characters), integer
`status` (0 healthy, 1 failing), safe concise `detail` (up to 1800 characters),
and optional integer `severity` (0–5, default 3). Preserve names across edits;
the collector's existing `check()` hashes names into Zabbix IDs. Use a service
prefix to avoid collisions with other services. Family is `functional/<slug>`.
Do not include credentials, request URLs with credentials, response bodies,
personal data, or exception messages in evidence. Generic failures expose only
exception class names. Modules own interpretation of successful responses.

`ctx.http(url, method='GET', headers=None, data=None, timeout=8,
max_bytes=262144, follow_redirects=False)` returns `status`, `headers`, and
`body` bytes, including HTTP error responses. HTTP(S) only; URL userinfo is
refused. Responses are bounded (maximum 1 MiB); timeouts are bounded by the
remaining service deadline. Redirects are disabled by default; opted-in
redirects must remain on the same origin, including when no explicit auth
header is present. Do not bypass this helper for service HTTP calls.
`ctx.now` is Unix time, `ctx.remaining()` reports remaining seconds, and
`ctx.kube` is the existing read-only Kubernetes client. Its RBAC has no Secret
read access; do not widen permissions to retrieve credentials.

JSON is an object passed unchanged to the module. Reserved keys: `interval`
(seconds, default 300, range 60–86400) and `deadline` (seconds, default 30,
range 1–30). Three daemon workers bound service concurrency independently of
infrastructure collection. Deadline begins when a worker starts a service. FIFO queue waiting does not
consume its execution budget; initial pending results remain unavailable and
cached results expire after interval plus deadline while awaiting a worker.
Late results are
ignored. Healthy cached results carry visible sample age; a missed deadline
fails the monitoring check and any prior service records. Initial pending,
missing module/config, malformed configuration, empty/invalid output, and
exceptions produce explicit monitoring failures. A hung worker can reduce
capacity but cannot block snapshots or manufacture fresh healthy results.

Credentials are mounted read-only from the optional namespace-local Secret
`zabbix-functional-credentials` at `/credentials`. `ctx.secret(key)` returns a
stripped nonempty value or raises; keys permit letters, digits, `_` and `-`.
Declare each service's exact required keys in its runbook and provision them
separately using the approved credential workflow. Never commit secret values
or print them. Missing Secret permits pod startup and produces visible service
failures where credentials are required. Creating/changing mounted credentials
does not grant API Secret read permissions.

Add service unit tests in `scripts/tests/test_service_<slug>.py`;
`scripts/test zabbix` discovers these automatically.

Keep checks modest and read-only: prove a useful application operation beyond
readiness (for example authenticated catalog/query reads), bound work and avoid
synthetic writes unless separately authorized. Existing Zabbix three-sample
trigger and severity policy remain in force. Run `scripts/test zabbix` and
`kubectl kustomize config/zabbix/manifests` before opening each service PR.
