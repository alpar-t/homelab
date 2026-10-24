# Buksi local media and space-driven cleanup

Movies and TV use `/var/mnt/disk1/media/movies` and
`/var/mnt/disk1/media/tv` on Buksi's first 4 TB HDD. Both folders share the
filesystem without quotas. `arr-stack` and `emby` are pinned to Buksi and mount
the folders with `hostPath.type: Directory`; a missing HDD prevents startup
instead of silently writing media to the root filesystem. The 600 GiB active
download area and application configs remain on Longhorn. Local media has no
Longhorn replica, snapshot, or weekly backup.

## Longhorn boundary

Only Buksi's `/var/mnt/disk2` HDD and `/var/lib/longhorn-ssd` are registered
with Longhorn. Its Kubernetes node has
`node.longhorn.io/create-default-disk=config`, and the
`node.longhorn.io/default-disks-config` annotation names only
`/var/mnt/disk2`. The annotation controls initial registration; removing an
existing Longhorn disk requires editing the Longhorn Node resource separately.
Do not re-add disk1 after a node rebuild. Verify both views:

```bash
kubectl get node buksi -o json | jq -r '.metadata.annotations["node.longhorn.io/default-disks-config"]'
kubectl -n longhorn-system get node.longhorn.io buksi -o json | jq '.spec.disks | to_entries | map({name:.key,path:.value.path})'
ssh core@buksi.local 'findmnt /var/mnt/disk1; df -h /var/mnt/disk1'
```

On 2026-10-23 the disk was evacuated with Longhorn's `evictionRequested` flag.
The final Tandoor replica rebuilt on Pufi while the Pamacs replica stayed
healthy, then disk1 was removed from Buksi's Longhorn Node `spec.disks`.

## Why the migration needed a staging copy

The old movie filesystem held about 1.0 TiB of files, while its single
Longhorn replica occupied about 3.2 TB on disk1 because of old snapshots.
There was not enough free space on disk1 for direct extraction. Movies were
copied with `rsync -aHA --numeric-ids` to a local folder on Buksi disk2 and
checked against the quiesced source. Media then ran from disk2 while ArgoCD
pruned the old Longhorn movie and TV PVCs. Once disk1 became empty, movies
were copied back to their final local folder. Preserve hardlinks with `-H`.
Do not delete the disk2 copy until the final disk1 mount and application paths
have been verified.

## Maintainerr cleanup

The earlier `Stale TV Cleanup` rule deleted episode files without checking
available storage. Sonarr recorded 449 episode-file deletions between July 1
and August 3, 2026, and the TV filesystem was empty on October 23 even though
series directories remained. Maintainerr's TV rule logged actions to remove
all episodes. Old Longhorn snapshot allocation is not proof that episodes are
present in the current filesystem.

The four cleanup groups are configured by
`config/media/maintainerr-pressure-rules.mjs` using Maintainerr's own API.
It appends an AND condition using Radarr/Sonarr's free space for the exact
movie or TV root folder. Watched candidates become eligible below 750 GiB
free, while stale unwatched candidates become eligible below 375 GiB. The
watched groups evaluate at 07:00, before the noon collection handler; stale
groups evaluate at 13:00 after watched cleanup has had a chance to reclaim
space, and the existing midnight handler processes them. Both paths report
the same free space because they share one disk. If a disk-space reading is
unavailable, the condition does not match.

To inspect or reconcile the rules, copy the script to Maintainerr's `/tmp`
and run it there without arguments for a read-only preview, then with
`--apply` to update the four groups. Confirm each saved rule and schedule.
The script refuses to update rules if Radarr and Sonarr do not report the same
shared-disk free space.

## Emby media-read alert

Emby's readiness probe fetches its public API and reads the first 4 KiB of a
movie file from its mounted local library. Zabbix reports a severity-5
`Emby movie file readable` failure if that pod readiness check fails. This
catches an empty or unreadable movie mount. It does not test an authenticated
playback stream or transcoding; those require a dedicated restricted test
account and separate synthetic request.
