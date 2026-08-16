# Baloo OLX deployment

Keep this public repository limited to the Kubernetes resources under
`config/baloo/manifests/`. Document agent behavior, account workflows, private
source layout, credentials, and end-to-end account tests only with the private
Baloo configuration.

## Deployment checks

After a manifest change, confirm the Baloo workloads roll out and every
container becomes ready:

```bash
kubectl -n baloo rollout status deployment/pinchtab
kubectl -n baloo rollout status deployment/openclaw
kubectl -n baloo get pods -l app.kubernetes.io/name=pinchtab
kubectl -n baloo get pod -l app.kubernetes.io/name=openclaw \
  -o jsonpath='{range .items[0].status.containerStatuses[*]}{.name}{"\t"}{.ready}{"\n"}{end}'
```

Do not commit credentials, browser state, account identifiers, conversation
content, private repository details, or private tool/skill procedures here.
