# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Keep Frigate 0.17.2 and its dependencies intact. Remove the two unbounded
# license-plate regex filters without changing recording or camera behavior.
FROM ghcr.io/blakeblackshear/frigate:0.17.2@sha256:d4351369984d4a9e2a49ac59736f6490856a7ea11f7790040746d21496967010

LABEL org.opencontainers.image.source="https://github.com/alpar-t/homelab" \
      org.opencontainers.image.description="Frigate 0.17.2 with exact license-plate event filters"

COPY patch_lpr_filter.py /tmp/patch_lpr_filter.py
RUN python3 /tmp/patch_lpr_filter.py \
    && rm /tmp/patch_lpr_filter.py
