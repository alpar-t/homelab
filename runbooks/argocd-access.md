# ArgoCD administrative access

ArgoCD has no public Kubernetes Ingress. The Cloudflare tunnel also has an
explicit terminal rule for `argocd.newjoy.ro`, placed before its wildcard
catch-all, so that hostname cannot reach ingress-nginx even if an Ingress is
accidentally recreated.

Public DNS for `*.newjoy.ro` is a wildcard. Consequently
`argocd.newjoy.ro` still resolves at the DNS layer, but cloudflared answers with
HTTP 404 and does not forward the request into the cluster. There is no
ArgoCD-specific DNS record to retain or remove.

## Administrative access

Use the Kubernetes API as the intentional administrative boundary:

```bash
kubectl -n argocd port-forward service/argocd-server 8443:443
```

Keep that command running and open `https://127.0.0.1:8443`. The ArgoCD server
certificate is not issued for localhost, so the browser will show a certificate
warning. For the CLI:

```bash
argocd login 127.0.0.1:8443 --insecure
```

This path works from the LAN or remotely whenever the workstation can reach the
Kubernetes API, including through Tailscale. It grants no new access: a caller
must already possess a working kubeconfig and ArgoCD credentials.

## Validation

After both `argocd-ingress` and `cloudflare-tunnel` have synced:

```bash
kubectl -n argocd get ingress argocd-server
kubectl -n cloudflared get configmap cloudflared-config \
  -o jsonpath='{.data.config\.yaml}'
curl -sS -o /dev/null -w '%{http_code}\n' https://argocd.newjoy.ro/
```

The Ingress lookup must return `NotFound`. The first cloudflared ingress rule
must match `argocd.newjoy.ro` and use `http_status:404`. The public request must
return 404, never an ArgoCD page or login redirect. Finally, run the port-forward
and confirm the UI loads locally.

## Rollback

Re-exposure must restore authentication before routing traffic:

1. Create a Cloudflare Access application for `argocd.newjoy.ro` with the
   intended identity allowlist.
2. Restore `config/argocd/ingress.yaml` from the commit before public access was
   removed.
3. Remove the terminal `argocd.newjoy.ro` rule from
   `config/cloudflare-tunnel/manifests/configmap.yaml`.
4. Commit and push both changes together, then wait for the `argocd-ingress` and
   `cloudflare-tunnel` Applications to become Synced and Healthy.
5. From outside the LAN, verify an unauthenticated request receives the
   Cloudflare Access challenge and cannot reach ArgoCD directly.
