# GitHub Actions Runner Controller

ARC runs ephemeral, repository-scoped GitHub Actions runners. Each repository
has a separate scale set while the controller and credential Secret are shared.

| Scale set | Repository | Purpose |
|---|---|---|
| `baloo-export-runners` | `alpar-t/baloo_export` | Export validation and publishing |
| `homelab-runners` | `alpar-t/homelab` | Homelab validation and daemonless image publishing |

- Controller chart: `gha-runner-scale-set-controller` 0.14.2 in `arc-systems`.
- Runner chart: `gha-runner-scale-set` 0.14.2 in `arc-runners`.
- Runner image: `actions-runner` 2.336.0, pinned by digest.
- Scale: zero idle runners, at most one active runner per repository.
- Isolation: no privileged container, no Docker, no runner ServiceAccount token, no inbound traffic, and no private-network egress except DNS and the Kubernetes API used by ARC.

## Credential

The `arc-runners/github-arc-token` Secret is created manually and is never committed. It contains the `github_token` key with a fine-grained PAT selected only for repositories that use ARC. Repository-level runner registration requires repository Administration read/write and Metadata read for both `alpar-t/baloo_export` and `alpar-t/homelab`.

To rotate it without putting the token in shell history:

```zsh
read -s "HOMELAB_ARC_TOKEN?Paste the replacement token, then press Enter: "
echo
print -rn -- "$HOMELAB_ARC_TOKEN" |
  kubectl -n arc-runners create secret generic github-arc-token \
    --from-file=github_token=/dev/stdin \
    --dry-run=client -o yaml |
  kubectl apply --server-side --field-manager=arc-secret-rotation -f -
unset HOMELAB_ARC_TOKEN
```

After rotation, restart the listener pod in `arc-runners` if it does not reconnect automatically.
