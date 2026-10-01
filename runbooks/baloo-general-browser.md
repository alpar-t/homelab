# Baloo general browser

`pinchtab-web` is the public-web PinchTab service. Its Kubernetes Secret is
`baloo/pinchtab-web-baloo` with key `token`; create it outside Git before
deploying the manifest. The OLX PinchTab service and its authenticated profile
are separate. Browserless stays available to the court-case monitor until its
PinchTab migration is verified.

The OpenClaw `general-browser` plugin creates a PinchTab agent session for each
Baloo agent. Its `web_browser` tool passes tab IDs explicitly and bounds text
and screenshot responses. The pod NetworkPolicy allows only public web egress.

## Diagnose failures

Inspect gateway failures and the matching PinchTab server logs:

```bash
kubectl -n baloo logs deploy/openclaw -c openclaw --since=1h | rg 'general_browser_failure'
kubectl -n baloo logs deploy/pinchtab-web --since=1h
```

Each gateway failure records the agent, action, OpenClaw session ID, tab ID,
public target host when known, elapsed time, and a bounded error code/message.
It does not record tokens, cookies, URL paths, query strings, or page content.
Use the tab and time to correlate the two logs. For a browser crash, also check
`kubectl -n baloo describe pod -l app.kubernetes.io/name=pinchtab-web`.

## Release check

After both repositories are deployed, test from Baloo Open WebUI with two
different agents browsing distinct public pages at the same time. Verify both
can read their own pages without tab mixups. Trigger a blocked private URL and
confirm the gateway writes one structured failure record without credentials.
Capture a public-page screenshot and verify that its image renders in WebUI and
its reported outbound file can be delivered. Leave the court-case browser and
OLX session untouched.
