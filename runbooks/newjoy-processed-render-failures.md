# Newjoy processed-render failures

The render pipeline keeps durable per-image failure records in OpenCloud under
`Processed Renders/<room>/<version>/`, alongside successful image provenance.
The private Baloo repository implements this in
`openclaw/tools/newjoy-render-failures.js` and
`openclaw/tools/newjoy-processed-renders.js`.

## Attempt limit and diagnostics

Each failed processing run writes `<processed-output-path>.failure.json` with
the original source path and ETag, processor version, attempt count, first and
last failure times, bounded diagnostic history, reason code, and a plain-language
explanation. Explicit provider error codes, moderation stage/categories, and
request IDs are included when the transport supplies them. An assistant's
statement that a tool rejected the request is recorded as `image_call_failed`;
it is not sufficient evidence to label a failure `moderation_blocked`.

After three failed processing runs, the record changes from `retry_pending`
to `failed`. The scheduled worker reports that transition, then skips the image
on later polls. Other images and projects continue. These are processing runs,
not individual HTTP requests: transient failures may receive one bounded retry
within a run. Authentication failures pause the shared service and do not consume
an image's attempt budget.

The OpenCloud record is authoritative and survives Gateway restarts and local
cooldown-cache expiry. Writes use ETag preconditions; malformed or unreadable
records block that image rather than silently resetting its budget. A failed
record write remains an operational error in the result/alert. The existing
Gateway-local retry cache remains only a backoff mechanism.

`list_pending_processed_renders` returns terminal records in `failed`.
`process_project_renders` returns new failures in `failed` and existing terminal
records in `previouslyFailed`; both are visible in WebUI tool responses. Failed
images are not counted as runnable `remaining` work and are not promoted as
processed website images.

## Retry after review

Ask for a specific image to be retried after reviewing its diagnostic. Pass
`retryFailedSourcePaths` to `process_project_renders`, for example:

```json
{
  "projectPath": "2026/SZABI",
  "retryFailedSourcePaths": ["Renders/Office room/v1/9.png"]
}
```

This resets the failure budget only for the named images and retains the previous
failure cycle in the next failure record. It cannot be combined with
`redoSourcePaths` or `storyOnly`. A successful processed output supersedes the
old failure record; the diagnostic file remains for reference. Replacing the
source image (new ETag) or upgrading the processor version also starts a new
budget because processed output and failure filenames include that identity.

The operator CLI supports the same explicit retry:

```sh
kubectl -n baloo exec deployment/openclaw -c openclaw -- \
  node /git/link/openclaw/tools/newjoy-processed-render-worker.js \
  --project 2026/SZABI --retry-failed-source 'Renders/Office room/v1/9.png'
```

Do not run this diagnostic as a routine health check: it invokes image generation.
Earlier local retry-cache entries lack source identity and detailed diagnostics,
so they are not imported into durable failure records automatically.
