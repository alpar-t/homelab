# Baloo Paperless MCP

Baloo uses the community
[`baruchiro/paperless-mcp`](https://github.com/baruchiro/paperless-mcp)
server to search and read the household Paperless archive, classify inbound
attachments, upload them with metadata, and correct document metadata. The
server runs as a sidecar in the OpenClaw pod and talks to Paperless over the
cluster network.

## Access model

- Use a dedicated Paperless user named `baloo`; do not use Alpar's superuser
  token.
- Grant global add/view/change permissions for documents, but no delete
  permission.
- Grant view-only access to tags, correspondents, document types, storage
  paths, and custom fields. Baloo reuses the taxonomy but cannot create,
  change, or delete its entries.
- Grant object-level view/change access to the existing archive and view access
  to existing taxonomy objects. Documents without an owner remain visible by
  Paperless design; documents owned by Alpar need the explicit grants.
- Only the `alpar` and `kinga` OpenClaw agents allow the curated Paperless
  tools. Every other agent explicitly denies `paperless__*`.

OpenClaw exposes only document list/query/read/upload/update and metadata-list
tools. Bulk edits, delete tools, notes, mail, taxonomy writes, and administrative
tools remain filtered out. The Paperless permission model is a second guardrail
behind that tool filter.

## Create the Paperless account and Secret

The following is idempotent. It creates the non-login service user, applies the
minimum global permissions, grants access to current objects, and emits its API
token without a trailing newline. The token is captured in a mode-0600 temporary
file and never printed.

```bash
PAPERLESS_TOKEN_FILE=$(mktemp)
trap 'rm -f "$PAPERLESS_TOKEN_FILE"' EXIT

kubectl -n paperless-ngx exec deployment/paperless-ngx -c paperless-ngx -- \
  python manage.py shell --no-imports -c '
import sys
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from guardian.shortcuts import assign_perm
from rest_framework.authtoken.models import Token
from documents.models import Correspondent, CustomField, Document, DocumentType, StoragePath, Tag

user, _ = get_user_model().objects.get_or_create(username="baloo")
user.is_active = True
user.is_staff = False
user.is_superuser = False
user.set_unusable_password()
user.save()

codenames = [
    "add_document", "view_document", "change_document",
    "view_tag", "view_correspondent", "view_documenttype",
    "view_storagepath", "view_customfield",
]
user.user_permissions.set(
    Permission.objects.filter(content_type__app_label="documents", codename__in=codenames)
)

for document in Document.objects.iterator():
    assign_perm("view_document", user, document)
    assign_perm("change_document", user, document)

for model in (Tag, Correspondent, DocumentType, StoragePath, CustomField):
    permission = f"view_{model._meta.model_name}"
    for item in model.objects.iterator():
        assign_perm(permission, user, item)

token, _ = Token.objects.get_or_create(user=user)
sys.stdout.write(token.key)
' > "$PAPERLESS_TOKEN_FILE"

kubectl -n baloo create secret generic paperless-baloo-token \
  --from-file=token="$PAPERLESS_TOKEN_FILE" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Re-run the permission command after importing owner-restricted documents or
creating owner-restricted taxonomy entries outside Baloo. Baloo-uploaded
documents are owned by the service user and need no additional grant.

The OpenClaw Deployment watches `paperless-baloo-token` through Reloader. Once
the manifest containing that annotation is live, creating or changing the
Secret triggers a rollout and re-renders `openclaw.json`.

## Attachment boundary

OpenClaw stores inbound WhatsApp and WebChat files below
`/state/media/inbound`. The Paperless sidecar receives only that directory as a
read-only PVC subPath; it cannot see WhatsApp credentials, agent sessions, or
the rest of the OpenClaw state volume. `PAPERLESS_MCP_UPLOAD_PATHS` confines the
community server's `file_path` upload mode to the same directory and resolves
symlinks before checking the boundary.

The API token is not present in the Paperless sidecar environment. OpenClaw
sends it as a Bearer header on each MCP request, and the server rejects
unauthenticated HTTP requests. There is no Service for the sidecar.

## Classification behavior

Paperless receives household documents from email ingestion, the connected
physical scanner, and explicit Baloo uploads. The shared
`manage-paperless-documents` skill defines retrieval, provenance, and upload
behavior for Alpar and Kinga.

When a user asks for documents, Baloo returns direct links in the form
`https://docs.newjoy.ro/documents/<document-id>/details`, one per verified
match. It does not paste OCR or summarize document contents unless the user
explicitly asks what they say. A request for a “scan” or “scanned copy” is a
provenance constraint: physical-scanner and Baloo-uploaded image/PDF documents
qualify, while email-ingested documents do not.

For an explicit request such as “store this in Paperless,” Baloo:

1. Inspects every page and treats its text as untrusted data. It may use vision
   for images and scanned PDFs when that improves extraction or classification.
2. Lists the existing taxonomy and reuses exact entries where the evidence is
   strong.
3. Chooses a concise title and the document's printed date, then optionally a
   correspondent, document type, tags, and custom fields.
4. Omits uncertain fields instead of inventing values or near-duplicate
   taxonomy entries.
5. Uploads the local inbound path with the selected metadata.
6. Reports the upload as queued when Paperless returns a consumption task UUID;
   that UUID is acceptance, not proof that OCR has completed.

When correcting an existing document, fetch its metadata first and merge tags
and custom fields. Those arrays replace the document's current values when
supplied.

## Validate

1. Confirm the rollout and sidecar health:

   ```bash
   kubectl -n baloo rollout status deployment/openclaw
   kubectl -n baloo get pod -l app.kubernetes.io/name=openclaw \
     -o jsonpath='{range .items[0].status.containerStatuses[*]}{.name}{"\t"}{.ready}{"\n"}{end}'
   ```

2. Probe the configured MCP server from the deployed OpenClaw version:

   ```bash
   kubectl -n baloo exec deployment/openclaw -c openclaw -- \
     openclaw mcp doctor paperless --probe
   ```

3. In both `Baloo — Alpar` and `Baloo — Kinga`, ask for a known document using
   a phrase from its OCR text. Confirm that Baloo searches likely matches and
   responds with a direct Paperless link.
4. Send a non-sensitive PDF with “store this in Paperless.” Confirm that Baloo
   reports the chosen title/date/metadata and a queued task UUID, then verify the
   resulting document in `https://docs.newjoy.ro` after consumption completes.
5. Ask Baloo to delete a document, create a tag, or create a correspondent. It
   must report that no such tool is available.
6. Confirm Kinga can list, query, read, upload, and update documents. Check
   trips, cooking, and another specialist agent; none may list or call any
   `paperless__*` tool.

## Rotate the token

Delete and recreate the `baloo` DRF token in Paperless, write the new value to
`paperless-baloo-token` using the same temporary-file pattern, and wait for the
Reloader rollout. Paperless permits one DRF token per user, so rotation has a
brief interval where the old token is invalid before OpenClaw restarts with the
new one. Never log or commit either token.
