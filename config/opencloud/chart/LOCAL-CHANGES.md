# Local chart changes

This chart is copied from the archived `opencloud-eu/helm` repository at
commit `72de94b25a89bfb3cf467cdf312e4166c55ded55` (chart version 0.2.3).
The upstream license is in [LICENSE](LICENSE). Keeping the chart here lets the
OpenCloud Application render a separate SSD thumbnail cache volume without a
post-sync mutation of the Deployment.

The local additions are:

- `opencloud.thumbnails.persistence` values and a separate PVC.
- A mount at OpenCloud's default `/var/lib/opencloud/thumbnails` path.
- A one-time copy of the existing cache from the data PVC in `init-config`.

The thumbnail cache is disposable. OpenCloud does not automatically remove
thumbnails for deleted files. The `local-ssd` StorageClass uses Rancher
local-path, so the requested PVC size is not a filesystem quota; monitor free
space on pufi and remove stale cache entries if it grows excessively.
