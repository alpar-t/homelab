FROM docker.io/library/node:22.18.0-alpine@sha256:1b2479dd35a99687d6638f5976fd235e26c5b37e8122f786fcd5fe231d63de5b

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts=false \
    && npm cache clean --force
COPY server.js ./

ENV NODE_ENV=production \
    IMAGE_TOOLS_HOST=127.0.0.1 \
    IMAGE_TOOLS_PORT=18807
USER node
EXPOSE 18807
CMD ["node", "server.js"]
