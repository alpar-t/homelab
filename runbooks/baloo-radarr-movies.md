# Baloo family movies and Radarr

The private `alpar-t/baloo` repository owns the `radarr-mcp.js` stdio MCP server,
Alpar's `family-movies` skill, tool policies, and `managed: family-movies` job.
The job runs Thursday at noon in `Europe/Bucharest`, automatically adds up to
three screened fresh titles, and delivers the verified results to Alpar's
private WhatsApp DM. Its tools cannot mark movies watched.

The MCP uses Radarr's internal service at
`http://radarr.media.svc.cluster.local:7878` and the existing household defaults:
quality profile 5 (`4K HDR`) and `/data/media/movies`. The helper validates these
against Radarr before adding anything; update its private configuration if the
household defaults change. It monitors only the chosen movie, not collections.

`GET /api/v3/movie`, `/api/v3/importlist/movie`, and `/api/v3/exclusions` supply
the combined inventory. Import-list movie results also contain Discover
suggestions: only nonempty `lists` indicates actual watchlist membership.
Pagination is bounded and guarded by an inventory hash so concurrent changes
cause a restart instead of silent omissions. The contract is based on the
[official Radarr API](https://radarr.video/docs/api/) and verified against the
deployed Radarr 6.1.1.

Downloaded is not watched. A watched report adds an import-list exclusion and
unmonitors the existing library movie using `PUT /api/v3/movie/editor`, without
deleting media. Existing exclusions are treated as no-download decisions, not
proof of playback. Movies watched outside Radarr need a user report. This does
not synchronize Emby watch history or cancel already-running downloads.

## Credential provision or rotation

The gateway mounts Secret `baloo/radarr-baloo` at `/var/run/secrets/radarr`.
Only the MCP reads `api-key`; the key is not rendered into OpenClaw JSON or
returned to the model. The optional mount preserves gateway startup when the
secret is absent, but movie tools then report a configuration error.

Copy the current key without printing it or putting it in command arguments:

```bash
set -o pipefail
kubectl -n media exec deployment/arr-stack -c radarr -- sh -c '
  key=$(sed -n "s:.*<ApiKey>\(.*\)</ApiKey>.*:\1:p" /config/config.xml)
  test -n "$key" || exit 1
  printf "%s" "$key"
' | kubectl -n baloo create secret generic radarr-baloo \
  --from-file=api-key=/dev/stdin --dry-run=client -o yaml \
  | kubectl apply -f -
```

Kubernetes updates the projected secret automatically after rotation; the MCP
reads the key for each API request. Adding the mount changes the Deployment
and requires its normal ArgoCD rollout. Subsequent private tool, skill, and
job changes follow git-sync and hot reload.

## Validation

In the private Baloo worktree:

```bash
openclaw/scripts/test radarr-mcp prompts cron
```

Check the config renderer and cron reconciler, then confirm the enabled job
with `openclaw cron list --all`. A manual `cron run` performs real additions and
sends a message, so use it only when a live recommendation run is intended.
For read-only smoke checks, use an MCP SDK client to list tools, page through
`list_movies`, and resolve a title with `lookup_movie`.
