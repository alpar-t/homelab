# Baloo OLX account skill

Baloo's existing `alpar` agent operates Alpar's OLX account through the
isolated Browserless browser. The source-controlled workflow lives in the
private `alpar-t/baloo` repository at `openclaw/skills/olx-account/`.

## Access model

- There is no dedicated OLX agent or channel binding. The existing `alpar`
  agent loads the `olx-account` skill for OLX account requests.
- OLX credentials exist only in the `olx-baloo` Kubernetes Secret and the
  `olx-auth-mcp` sidecar environment. They are never added to `openclaw.json`,
  an agent workspace, a prompt, or browser-tool arguments.
- Every OLX browser action explicitly uses the dedicated `olx` profile. It
  points to the existing Browserless service but keeps OLX tabs and session
  state separate from the default `cluster` profile.
- Browserless launches `olx` with Chromium `userDataDir=/profiles/olx`, backed
  by the `browser-olx-profile` PVC. Successful login cookies therefore survive
  browser and OpenClaw pod restarts; the other profiles remain ephemeral.
- The helper exposes only `olx-auth__fill_credentials`. It verifies that the
  supplied tab is on `https://login.olx.ro`, fills the visible fields, and
  neither clicks nor submits. The LLM handles the changing page UI.
- Only `alpar` allows `olx-auth__fill_credentials`; every other agent
  explicitly denies `olx-auth__*`.
- CAPTCHA, MFA, and new-device verification stop the workflow for human
  action. Do not attempt to bypass them.

The `olx` profile provides session separation, not access control: OpenClaw's
profiles are gateway-global, so another agent with the generic `browser` tool
could deliberately select it. Persisted OLX cookies are credentials in their
own right and inherit that limitation. Its Browserless URL deliberately has no
`trackingId`: Browserless rejects a second connection to an active tracking ID,
whereas the LLM and credential filler need multiple commands against the same
OpenClaw-owned profile session. Its explicit `timeout=900000` query also keeps
the OLX CDP URL distinct from the court profile without changing the effective
server timeout; identical remote CDP URLs can share an OpenClaw controller and
mix tabs.

The PVC uses `longhorn-ssd-noreplica`: this session state is intentionally not
backed up and losing it only requires logging in again. The browser Deployment
uses `Recreate` because two pods must never operate on the same Chromium
user-data directory.

## Create or rotate the Kubernetes Secret

Do not paste the password into chat or commit it to git. Enter it in a local
shell without echoing it, then create the Secret:

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

The Deployment watches `olx-baloo` through Reloader. Creating or updating the
Secret triggers a rollout after the manifest with that annotation is deployed.

## Supported workflow

On demand, the skill can:

1. Open the saved land search around Petreștii de Jos.
2. Inspect only results OLX itself identifies as new or unseen.
3. Report only adverts whose displayed location is Petreștii de Jos, excluding
   nearby radius matches.
4. Check unread OLX threads when asked and propose a reply in the sender's
   language.
5. Send only the exact proposed reply after explicit confirmation and after
   checking that no newer incoming message changed the context.

The first version does not create, edit, renew, promote, or price adverts and
does not run a recurring poll. Photo inspection, listing creation, negotiation
limits, and persistent price memory are deferred.

## Validate

1. Confirm all containers are ready:

   ```bash
   kubectl -n baloo rollout status deployment/openclaw
   kubectl -n baloo get pod -l app.kubernetes.io/name=openclaw \
     -o jsonpath='{range .items[0].status.containerStatuses[*]}{.name}{"\t"}{.ready}{"\n"}{end}'
   ```

2. Probe the credential helper from the OpenClaw container:

   ```bash
   kubectl -n baloo exec deployment/openclaw -c openclaw -- \
     openclaw mcp doctor olx-auth --probe
   ```

3. Confirm `openclaw browser profiles --json` lists distinct `cluster` and
   `olx` profiles.
4. After one successful login, restart the browser Deployment and open OLX
   again with profile `olx`. Confirm it remains authenticated without invoking
   the credential helper.
5. In `Baloo — Alpar`, ask: “Check my OLX saved land search.” Confirm every
   browser call uses `olx`, the helper fills but does not submit credentials,
   and the result contains only OLX-marked new adverts whose displayed location
   is Petreștii de Jos.
6. Ask it to check unread messages. Confirm it shows a draft but does not type
   or send it. Approve the exact draft in a second message and verify it appears
   in the OLX thread.
7. Ask another Baloo agent to access OLX. It must not have any `olx-auth__*`
   tool.

If login stops for verification, do not loop retries. The current deployment
does not expose an interactive Browserless view, so retry later; solving a
challenge in an unrelated manual browser does not transfer that browser's
session. Never weaken the browser NetworkPolicy or expose the control API
outside the pod to work around account verification.
