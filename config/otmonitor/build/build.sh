#!/bin/bash
set -euo pipefail

# OTMonitor Docker Image Build Script
# Usage: ./build.sh [push]
# Builds for linux/amd64 (x86_64) from ARM Mac

IMAGE_NAME="ghcr.io/alpar-t/otmonitor"
TAG="${TAG:-latest}"
PLATFORM="linux/amd64"

# Ensure buildx is available
if ! docker buildx version &>/dev/null; then
    echo "Error: docker buildx is required for cross-platform builds"
    exit 1
fi

# Create/use a builder that supports multi-platform
BUILDER_NAME="otmonitor-builder"
if ! docker buildx inspect "$BUILDER_NAME" &>/dev/null; then
    echo "Creating buildx builder..."
    docker buildx create --name "$BUILDER_NAME" --use
fi
docker buildx use "$BUILDER_NAME"

if [[ "${1:-}" == "push" ]]; then
    echo "Building and pushing ${IMAGE_NAME}:${TAG} for ${PLATFORM}..."
    docker buildx build \
        --platform "$PLATFORM" \
        --tag "${IMAGE_NAME}:${TAG}" \
        --push \
        .
    echo "✓ Pushed ${IMAGE_NAME}:${TAG}"
else
    echo "Building ${IMAGE_NAME}:${TAG} for ${PLATFORM}..."
    # Load into local docker (only works for single platform matching host)
    # For cross-platform, we need to push directly
    docker buildx build \
        --platform "$PLATFORM" \
        --tag "${IMAGE_NAME}:${TAG}" \
        --load \
        . 2>/dev/null || {
            echo ""
            echo "Note: Cannot load cross-platform image locally on ARM Mac."
            echo "Use './build.sh push' to build and push directly to registry."
            exit 0
        }
    echo ""
    echo "Image built successfully!"
    echo "To push, run: ./build.sh push"
fi
