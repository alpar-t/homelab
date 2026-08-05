# Sure removal

This intentionally empty ArgoCD source makes the existing `sure` Application
prune all formerly managed Sure resources. After Argo reports no managed
resources for the application, remove this directory and `apps/sure.yaml`.
