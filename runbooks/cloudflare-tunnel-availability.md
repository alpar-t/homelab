# Cloudflare Tunnel availability

All public `*.newjoy.ro` HTTP traffic enters the cluster through the
`cloudflared` Deployment and then the `ingress-nginx-controller` Service. Keep
both layers node-redundant: three replicas, spread one per Kubernetes hostname,
with a PodDisruptionBudget requiring two available.

Each `cloudflared` pod uses the same locally managed tunnel credentials. This is
intentional: the pods are replicas of one tunnel, and Cloudflare sends new
requests to any connected replica.

## Resource floor

`cloudflared` needs at least a `128Mi` memory request and `256Mi` limit in this
cluster. The old `64Mi` request and `128Mi` limit caused repeated memory-cgroup
OOM kills. Do not lower the limit without observing a representative traffic
window and confirming peak working set remains safely below the new value.

## August 2026 incidents

### 2026-08-06: `newjoy.ro` HTTP 530

Zincati began a planned Fedora CoreOS update reboot of `buksi` at 17:08 EEST.
Both nominally redundant tunnel pods had been scheduled on that node, so the
tunnel temporarily had no connector. Cloudflare returned 530; ingress and the
landing page remained healthy. The first retained successful external monitor
request reached the landing page at 17:11 EEST.

### 2026-08-07: `auth.newjoy.ro` HTTP 502

One connector entered an OOM/restart loop beginning at 17:42 EEST. The other was
OOM-killed at 18:10 and again at 18:11:52. The external alert began seconds later
at 18:12. Pocket ID did not restart; both tunnel connectors were unavailable.

Commit `21a5eb8` raised the tunnel to three replicas, enforced one per node,
raised memory to `128Mi` requested and `256Mi` limited, and changed the tunnel
PDB to `minAvailable: 2`. It also applied the same three-node layout to ingress
and the root landing page. Baloo commit `be79a5b` made fewer than two Ready
connectors or a recent connector OOM/restart loop pageable conditions.

## Validate

```bash
kubectl get deployment,pod,pdb -n cloudflared -o wide
kubectl get deployment,pod,pdb -n ingress-nginx -o wide
kubectl top pods -n cloudflared --containers
curl -I https://newjoy.ro/
curl -I https://auth.newjoy.ro/healthz
```

Expect three Ready tunnel and ingress pods, with one of each on `buksi`,
`pamacs`, and `pufi`; each PDB should show `minAvailable: 2`. Treat any connector
OOM kill as a capacity fault even when the other replicas hide public impact.

For a reported Cloudflare error, use ingress access logs to place the failure:
if the external probe never appears, the request failed at Cloudflare/tunnel;
if it appears with an upstream error, continue through ingress endpoints and
the application logs.
