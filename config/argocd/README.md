# ArgoCD access resources

This directory intentionally contains no Kubernetes manifests. Keep the
`argocd-ingress` Application in `apps/` so ArgoCD continues to own this path and
prunes any previously managed public Ingress. That Application deliberately
sets `automated.allowEmpty: true` so the empty desired state is valid.

ArgoCD administration uses a local `kubectl port-forward`; see
`runbooks/argocd-access.md`.
