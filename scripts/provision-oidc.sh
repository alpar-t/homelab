#!/usr/bin/env bash
# Provisions an OIDC client in Pocket ID and writes the credentials as a
# Kubernetes secret in the target namespace.
#
# Prerequisites:
#   kubectl create secret generic pocket-id-api-key -n pocket-id \
#     --from-literal=api_key=<key-from-auth.newjoy.ro/settings/admin/api-keys>
#
# Usage:
#   ./scripts/provision-oidc.sh <app-name> <app-url> <callback-url> <target-namespace>
#
# Example (TREK):
#   ./scripts/provision-oidc.sh trek \
#     https://travel.newjoy.ro \
#     https://travel.newjoy.ro/api/auth/oidc/callback \
#     trek

set -euo pipefail

APP_NAME=${1:?Usage: $0 <app-name> <app-url> <callback-url> <target-namespace>}
APP_URL=${2:?}
CALLBACK_URL=${3:?}
TARGET_NS=${4:?}

JOB_NAME="oidc-provision-${APP_NAME}-$(date +%s)"

echo "Launching provisioner job: $JOB_NAME"

kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: pocket-id
  labels:
    app: oidc-provisioner
    target-app: ${APP_NAME}
spec:
  ttlSecondsAfterFinished: 600
  template:
    spec:
      serviceAccountName: oidc-provisioner
      restartPolicy: Never
      containers:
        - name: provisioner
          image: curlimages/curl:latest
          command: ["/bin/sh", "/scripts/provision.sh"]
          env:
            - name: APP_NAME
              value: "${APP_NAME}"
            - name: APP_URL
              value: "${APP_URL}"
            - name: CALLBACK_URL
              value: "${CALLBACK_URL}"
            - name: TARGET_NS
              value: "${TARGET_NS}"
          volumeMounts:
            - name: script
              mountPath: /scripts
      volumes:
        - name: script
          configMap:
            name: oidc-provisioner-script
            defaultMode: 0755
EOF

echo ""
echo "Follow logs:"
echo "  kubectl logs -n pocket-id -l job-name=${JOB_NAME} -f"
echo ""
echo "Or wait for completion:"
echo "  kubectl wait job/${JOB_NAME} -n pocket-id --for=condition=complete --timeout=60s"
