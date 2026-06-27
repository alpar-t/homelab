# Finding WhatsApp channel IDs for Baloo bindings

`config/baloo/openclaw.json` binds each Baloo agent (direct-message, cooking,
garden, …) to a WhatsApp peer via `bindings[].match.peer`:

- `kind: direct` + an E.164 number (e.g. `+40744931029`) for DMs
- `kind: group` + a group JID (`<digits>@g.us`) for group chats

The values are interpolated from secrets in `baloo-secrets`
(`BALOO_OWNER_PHONE`, `KINGA_PHONE`, `BALOO_SHEF_GROUP`, `BALOO_GARDEN_GROUP`,
…). To wire up a new binding you need the channel ID. WhatsApp doesn't expose
group JIDs in the mobile UI, so the canonical way is to send one message into
the target chat and read the ID out of OpenClaw's logs.

## Capture an ID from the logs

1. From the device you own, send any message into the chat you want to bind
   (DM or group). For groups, **don't** @-mention Baloo — that triggers
   activation; we just want the routing event.
2. Read the inbound-message event from the openclaw container:

   ```bash
   POD=$(kubectl -n baloo get pod -l app=openclaw -o jsonpath='{.items[0].metadata.name}')
   DAY=$(date -u +%Y-%m-%d)
   kubectl -n baloo exec "$POD" -c openclaw -- \
     cat /tmp/openclaw/openclaw-${DAY}.log \
     | python3 -c "
   import sys, json
   for line in sys.stdin:
       try: d = json.loads(line)
       except: continue
       if d.get('message') != 'inbound message': continue
       p = d.get('1') or {}
       print(d.get('time',''), p.get('from'), '->', p.get('to'), '|', p.get('body','')[:60])
   " | tail -20
   ```

3. The `from` field is the channel ID:
   - DM: `+40744931029` (E.164)
   - Group: `120363428319977593@g.us`

The shorter `kubectl logs` stdout (`kubectl -n baloo logs $POD -c openclaw`)
only prints a summary line (`Inbound message <from> -> <to> (direct, N chars)`)
and **omits group JIDs entirely** — always read `/tmp/openclaw/openclaw-*.log`
inside the pod when chasing group IDs.

## Wire the ID into a binding

1. Pick the env-var slot in `config/baloo/openclaw.json`
   (e.g. `${BALOO_GARDEN_GROUP}`) — or add a new one.
2. Put the value in the `baloo-secrets` secret. The secret is rendered into
   the openclaw container by the `render-config` init container; ArgoCD
   manages it via `apps/baloo.yaml`. Patch directly when iterating:

   ```bash
   VAL=$(printf '%s' '120363428319977593@g.us' | base64)
   kubectl -n baloo patch secret baloo-secrets \
     --type=merge -p "{\"data\":{\"BALOO_GARDEN_GROUP\":\"$VAL\"}}"
   kubectl -n baloo rollout restart deploy/openclaw
   ```

   For a durable change, update the secret manifest under
   `config/baloo/manifests/` and let Argo reconcile.

3. Confirm at startup: openclaw prints a warning at boot for any binding whose
   env var is still unresolved, e.g.
   `bindings[3].match.peer.id: Missing env var "BALOO_GARDEN_GROUP"`.
   No warning → all bindings interpolated.

## Group messages still ignored after binding?

Routing is one half; activation is the other. By default, OpenClaw skips
group messages unless the bot is @-mentioned or quoted. The skip is silent
on stdout but visible in the per-pod log file as
`Group message stored for context (no mention detected) in <jid>: <body>`.

Two ways to make Baloo respond to plain messages in a group:

- **@-mention** the bot's number (or reply-quote one of its messages) — the
  one-shot way.
- **`/activation always`** sent in the group by the owner — flips
  `groupActivation` for that conversation so every subsequent message routes
  to the agent. Stored in the session store; persists across restarts.
  Note the spelling: the parser matches `/activation` (with the trailing
  `-ion`), not `/activate`. Modes are `always` or `mention`.

If a group ID is configured correctly but nothing happens, check
`/tmp/openclaw/openclaw-*.log` for the "stored for context" line before
suspecting the binding.
