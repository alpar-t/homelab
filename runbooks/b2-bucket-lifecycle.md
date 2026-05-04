# B2 Bucket Lifecycle (homelab-longhorn-backup)

The B2 bucket `homelab-longhorn-backup` stores Longhorn volume backups
and CNPG (barman) WAL/base archives. It is **not** managed by ArgoCD —
bucket-level config lives only on the B2 side, so this runbook exists
to keep the intended state recorded.

## Versioning policy

B2 has **versioning enabled** at the file level — that's a B2 default
that can't be turned off via the S3-compatible API, only managed via
lifecycle rules. We don't want versioning semantics for backups
because:

- Longhorn never overwrites — every backup has a unique name, retention
  manages deletion. A "previous version" of a deleted backup is never
  what you want to recover.
- CNPG/barman is the same: WAL files have unique names, obsolete ones
  are deleted by retention.
- Without a lifecycle rule, every deleted object becomes a hidden
  noncurrent version that you keep paying for forever. We hit this on
  2026-04-30: bucket showed ~17 TB while Longhorn thought ~3 TB was
  live — the rest was 5 months of pruned backups that had been
  silently retained as hidden versions.

## Active lifecycle rule

```json
{
  "Rules": [
    {
      "ID": "purge-hidden-versions",
      "Status": "Enabled",
      "Filter": {"Prefix": ""},
      "NoncurrentVersionExpiration": {"NoncurrentDays": 1}
    }
  ]
}
```

Effect: a deleted object becomes a hidden noncurrent version that lives
for 1 day, then B2's lifecycle scanner removes it. Practically this is
"versioning off with a 24h grace window."

## How to apply / verify

Credentials live in `secret/longhorn-system/backblaze-backup-credentials`
(keys: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINTS`).

```bash
# Load creds
eval "$(kubectl get secret -n longhorn-system backblaze-backup-credentials \
  -o jsonpath='{.data}' | python3 -c "
import json, base64, sys
d = json.load(sys.stdin)
for k in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_ENDPOINTS']:
  print(f'export {k.replace(\"AWS_ENDPOINTS\",\"AWS_ENDPOINT_URL\")}={base64.b64decode(d[k]).decode().strip()}')
")"

# Verify lifecycle is in place
aws --endpoint-url=$AWS_ENDPOINT_URL s3api get-bucket-lifecycle-configuration \
  --bucket homelab-longhorn-backup
```

To re-apply if ever lost:

```bash
aws --endpoint-url=$AWS_ENDPOINT_URL s3api put-bucket-lifecycle-configuration \
  --bucket homelab-longhorn-backup \
  --lifecycle-configuration '{"Rules":[{"ID":"purge-hidden-versions","Status":"Enabled","Filter":{"Prefix":""},"NoncurrentVersionExpiration":{"NoncurrentDays":1}}]}'
```

## Manual purge (when you can't wait for the lifecycle scanner)

The scanner runs ~daily. If you need an immediate cleanup of
already-accumulated hidden versions:

```bash
# Delete ONLY noncurrent versions, NOT delete markers.
#
# WARNING: do not delete delete markers in bulk. A delete marker is the
# version that "hides" the previous current version from the bucket's
# logical view. Removing the delete marker makes the noncurrent version
# underneath visible again — i.e. it un-deletes the object. Lost ~5 TB
# of effort to this on 2026-05-02 by deleting markers; Longhorn's
# BackupTarget poll then re-discovered the resurrected chunks and
# re-created BackupVolume CRs.
#
# Safe rule: delete noncurrent versions only. Delete markers are tiny
# (zero bytes) and will be cleaned up over time, or you can rely on
# the lifecycle rule.
aws --endpoint-url=$AWS_ENDPOINT_URL s3api list-object-versions \
  --bucket homelab-longhorn-backup --output json | \
  python3 -c '
import json, sys, subprocess, os
endpoint = os.environ["AWS_ENDPOINT_URL"]
bucket = "homelab-longhorn-backup"
data = json.load(sys.stdin)
to_del = [{"Key": v["Key"], "VersionId": v["VersionId"]}
          for v in data.get("Versions", []) if not v["IsLatest"]]
# Intentionally NOT including data["DeleteMarkers"] — see WARNING above.
for i in range(0, len(to_del), 1000):
    payload = {"Objects": to_del[i:i+1000], "Quiet": True}
    subprocess.run(["aws", "--endpoint-url", endpoint, "s3api",
                    "delete-objects", "--bucket", bucket,
                    "--delete", json.dumps(payload)], check=True)
    print(f"deleted {min(i+1000, len(to_del))}/{len(to_del)}")
'
```

For very large purges, prefer running this as a long background task —
millions of small chunks may take hours.
