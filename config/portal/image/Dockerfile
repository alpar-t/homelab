FROM docker.io/library/nginx:alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752

COPY manifests/assets/ /usr/share/nginx/html/
COPY manifests/nginx/default.conf /etc/nginx/conf.d/default.conf
