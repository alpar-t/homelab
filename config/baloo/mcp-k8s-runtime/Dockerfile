# Keep the upstream v4.1.9 application and production dependencies while
# leaving its cloud CLIs and package-management tools in the source stage.
FROM docker.io/flux159/mcp-server-kubernetes:v4.1.9@sha256:cab5f1aad3ef768619a014b82c926e4089d4f21eb989e116116a577300ece4b4 AS upstream

FROM registry.k8s.io/kubectl:v1.34.6@sha256:6caded2d48c26684fb0208384f80678adf538c136032f88ed5ce35b1779880fa AS kubectl

# Match upstream's Node major and Debian release for native module ABI.
FROM docker.io/library/node:24-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205

LABEL org.opencontainers.image.source="https://github.com/alpar-t/homelab" \
      org.opencontainers.image.description="Read-only Baloo Kubernetes MCP runtime"

WORKDIR /usr/local/app
COPY --from=upstream --chown=1000:1000 /usr/local/app/dist ./dist
COPY --from=upstream --chown=1000:1000 /usr/local/app/node_modules ./node_modules
COPY --from=upstream --chown=1000:1000 /usr/local/app/package.json ./package.json
COPY --from=upstream --chown=1000:1000 /usr/local/app/package-lock.json ./package-lock.json
COPY --from=kubectl /bin/kubectl /usr/local/bin/kubectl

RUN node --version \
    && kubectl version --client=true

ENV NODE_ENV=production \
    HOME=/tmp \
    TMPDIR=/tmp

USER 1000:1000
EXPOSE 3000
CMD ["node", "dist/index.js"]
