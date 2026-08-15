# Baloo OLX account skill

Baloo's existing `alpar` agent operates Alpar's OLX account with the
source-controlled `olx-account` skill from the private `alpar-t/baloo`
repository. PinchTab is the OLX-only browser canary; Browserless remains the
general browser backend until this evaluation is complete.

## Access and isolation model

- There is no dedicated OLX agent or channel. Only `alpar` allows the exact
  `pinchtab` tool and `olx-auth__fill_credentials`; every other agent explicitly
  denies `pinchtab` and `olx-auth__*`.
- PinchTab has its own pod, ClusterIP Service, NetworkPolicy, API token, and
  2-GiB PVC. It cannot reach cluster or LAN addresses and accepts API traffic
  only from the OpenClaw pod.
- PinchTab 0.15.1 checks for `/.dockerenv` before adding Chromium's required
  container-mode `--no-sandbox` flag. k3s/containerd does not create that
  Docker marker, so the ConfigMap mounts an empty marker file. Do not replace
  this with elevated capabilities or `allowPrivilegeEscalation`; the container
  remains the Chromium isolation boundary.
- PinchTab permits top-level navigation only to `olx.ro` and its subdomains.
  JavaScript evaluation, cookies API access, downloads, uploads, network
  interception, clipboard access, macros, file URLs, and state export stay
  disabled. Interactive screencast is enabled for operator handoff.
- The named `olx` Chromium profile lives at `/data/profiles/olx` on the
  `pinchtab-data` PVC. Login cookies and browser state survive instance and pod
  restarts. The PVC uses `longhorn-ssd-noreplica`: it is replaceable login state,
  receives no recurring backup, and loss requires signing in again.
- PinchTab uses the `simple` strategy. A shorthand browser request lazily starts
  one instance with the default `olx` profile. Explicit orchestration requests
  can start additional instances with separate persistent or disposable
  profiles; a Chromium profile may never be opened by two instances at once.
- The OpenClaw plugin exposes only its primary `pinchtab` tool. Its optional
  `browser` compatibility alias is disabled, so Browserless remains the sole
  generic `browser` implementation. The plugin is installed from the exact
  reviewed npm version `@pinchtab/pinchtab@0.15.1`.

Profile separation is useful containment, not a substitute for authorization.
An agent with the PinchTab API token could control the authenticated session,
which is why the token is absent from prompts and only `alpar` receives the
tool. Persisted cookies are credentials too. Preserve this pattern for future
browser-based account flows: a named persistent profile, a narrowly allowed
agent/tool, domain restrictions, private network isolation, and explicit human
confirmation for consequential writes.

## Credential helper

OLX credentials exist only in the `olx-baloo` Kubernetes Secret and the
`olx-auth-mcp` sidecar environment. The helper receives the PinchTab API token,
verifies the supplied tab is exactly on `https://login.olx.ro`, identifies the
visible localized email and password fields, and fills them through PinchTab.
It never returns credentials and never clicks or submits. The LLM handles the
changing page UI without seeing the password.

CAPTCHA, MFA, and new-device verification require human action. PinchTab's
handoff record coordinates that pause but is not a lock or security boundary;
never loop challenge attempts or claim the agent solved a challenge.

## Create or rotate secrets

Do not paste either token or password into chat or commit it to git.

Create the PinchTab control-plane token once before deploying the manifests:

```bash
pinchtab_token="$(openssl rand -hex 32)"
kubectl -n baloo create secret generic pinchtab-baloo \
  --from-literal=token="$pinchtab_token" \
  --dry-run=client -o yaml | kubectl apply -f -
unset pinchtab_token
```

Create or rotate the OLX credentials without echoing the password:

```bash
read -r "olx_email?OLX email: "
read -rs "olx_password?OLX password: "
echo
kubectl -n baloo create secret generic olx-baloo \
  --from-literal=email="$olx_email" \
  --from-literal=password="$olx_password" \
  --dry-run=client -o yaml | kubectl apply -f -
unset olx_email olx_password
```

Reloader restarts the affected Deployments after either Secret is changed.

## Supported workflow

On demand, the skill can:

1. Open the saved land search around Petreștii de Jos.
2. Inspect only results OLX identifies as new or unseen.
3. Report only adverts whose displayed location is Petreștii de Jos, excluding
   nearby radius matches.
4. Check unread OLX threads when asked and propose a reply in the sender's
   language.
5. Send only the exact proposed reply after explicit confirmation and after
   checking that no newer incoming message changed the context.

The first version does not create, edit, renew, promote, or price adverts and
does not run a recurring poll. Photo inspection, listing creation, negotiation
limits, and persistent price memory are deferred.

## Operator view for login or CAPTCHA

The dashboard is intentionally not exposed through an Ingress. Forward it only
for the duration of a human handoff:

```bash
kubectl -n baloo port-forward service/pinchtab 9867:9867
```

Open `http://127.0.0.1:9867/` locally. The dashboard can view and interact with
the running tab through its screencast. Close the port-forward afterward. The
API still requires the token; obtain it locally only when the dashboard asks:

```bash
kubectl -n baloo get secret pinchtab-baloo \
  -o jsonpath='{.data.token}' | base64 --decode
```

## Validate and roll back

1. Confirm both Deployments and every OpenClaw container are ready:

   ```bash
   kubectl -n baloo rollout status deployment/pinchtab
   kubectl -n baloo rollout status deployment/openclaw
   kubectl -n baloo get pods -l app.kubernetes.io/name=pinchtab
   kubectl -n baloo get pod -l app.kubernetes.io/name=openclaw \
     -o jsonpath='{range .items[0].status.containerStatuses[*]}{.name}{"\t"}{.ready}{"\n"}{end}'
   ```

2. Confirm the runtime plugin is exactly `0.15.1`, its compatibility alias is
   disabled, and `alpar` alone has the `pinchtab` tool.
3. Probe `olx-auth` and verify the helper fills an OLX login tab without
   submitting it.
4. Start two explicit disposable instances and confirm they have distinct
   profile directories and those directories disappear when stopped.
5. Start an explicit named test profile, record state, restart that instance,
   and verify the state remains. Restart the PinchTab pod and repeat.
6. Verify a second instance cannot open a profile already locked by the first.
7. Log into OLX, restart PinchTab, and confirm the named `olx` profile remains
   authenticated. Exercise saved-search and unread-message drafting; do not send
   a reply without a second-message confirmation.
8. Confirm Browserless still handles ordinary `browser` calls.

For rollback, revert the PinchTab manifest/config commits. Browserless remains
deployed throughout. Argo CD will remove `pinchtab` and its replaceable PVC;
that deletes PinchTab's OLX login state and cannot be recovered from cluster
backups. The removed `browser-olx-profile` PVC from the earlier Browserless
experiment is likewise replaceable and intentionally not retained.
