#!/usr/bin/env python3
"""Resolve a registry image tag to a Linux/amd64 manifest-list digest."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from typing import NoReturn


UNSTABLE = re.compile(
    r"(?:^|[-_.])(alpha|beta|rc|pre|preview|dev|nightly|snapshot|master|main|latest|sha|sig|att|metadata)(?:[-_.]|$)",
    re.IGNORECASE,
)
ARCH_SUFFIX = re.compile(r"(?:^|[-_.])(amd64|arm64|aarch64|armv7|ppc64le|s390x)$", re.IGNORECASE)
VERSION_LIKE = re.compile(r"^v?\d+(?:[._-]\d+)+(?:[-+][a-zA-Z0-9][a-zA-Z0-9._-]*)?$")


def fail(message: str) -> NoReturn:
    print(f"resolve-container-image: {message}", file=sys.stderr)
    raise SystemExit(1)


def run_skopeo(*arguments: str) -> str:
    command = ["skopeo", *arguments]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        fail(f"{' '.join(command)} failed: {detail}")
    return result.stdout


def split_embedded_tag(image: str) -> tuple[str, str | None]:
    if "@" in image:
        fail("pass an unpinned image; the script produces the digest pin")
    image = image.removeprefix("docker://")
    tail = image.rsplit("/", 1)[-1]
    if ":" not in tail:
        return image, None
    name, tag = image.rsplit(":", 1)
    return name, tag


def canonical_image(image: str) -> str:
    if "/" not in image:
        return f"docker.io/library/{image}"
    first = image.split("/", 1)[0]
    if "." not in first and ":" not in first and first != "localhost":
        return f"docker.io/{image}"
    return image


def natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    parts = re.split(r"(\d+)", value.lstrip("vV"))
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in parts
        if part
    )


def candidate_tags(image: str, allow_prerelease: bool) -> list[str]:
    payload = run_skopeo("list-tags", f"docker://{image}")
    try:
        tags = json.loads(payload)["Tags"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        fail(f"unexpected tag-list response: {error}")

    candidates = []
    for tag in tags:
        if not isinstance(tag, str) or not VERSION_LIKE.fullmatch(tag):
            continue
        if ARCH_SUFFIX.search(tag):
            continue
        if not allow_prerelease and UNSTABLE.search(tag):
            continue
        candidates.append(tag)
    return sorted(set(candidates), key=natural_key, reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve an image tag through the registry and print a reproducible "
            "Linux/amd64 tag@digest reference. With no tag, select the highest "
            "stable version-like tag."
        )
    )
    parser.add_argument("image", help="image repository, with an optional embedded tag")
    parser.add_argument("tag", nargs="?", help="explicit tag to resolve")
    parser.add_argument("--list", action="store_true", help="list stable candidate tags without resolving one")
    parser.add_argument("--limit", type=int, default=20, help="candidate count for --list (default: 20)")
    parser.add_argument("--allow-prerelease", action="store_true", help="include version-like prerelease tags")
    parser.add_argument("--os", default="linux", help="required image OS (default: linux)")
    parser.add_argument("--arch", default="amd64", help="required image architecture (default: amd64)")
    args = parser.parse_args()

    if not shutil.which("skopeo"):
        fail("skopeo is not installed or not on PATH")
    if args.limit < 1:
        fail("--limit must be positive")

    raw_image, embedded_tag = split_embedded_tag(args.image)
    if args.tag and embedded_tag:
        fail("tag was supplied both inside IMAGE and as the TAG argument")
    image = canonical_image(raw_image)
    tag = args.tag or embedded_tag

    if args.list:
        if tag:
            fail("--list cannot be combined with a tag")
        tags = candidate_tags(image, args.allow_prerelease)
        if not tags:
            fail("the registry returned no matching version-like tags; pass an explicit tag")
        for candidate in tags[: args.limit]:
            print(candidate)
        return

    if not tag:
        tags = candidate_tags(image, args.allow_prerelease)
        if not tags:
            fail("the registry returned no stable version-like tags; pass an explicit tag")
        tag = tags[0]

    reference = f"{image}:{tag}"
    template = "{{.Digest}}|{{.Os}}|{{.Architecture}}"
    inspection = run_skopeo(
        "inspect",
        "--override-os",
        args.os,
        "--override-arch",
        args.arch,
        "--format",
        template,
        f"docker://{reference}",
    ).strip()
    try:
        digest, resolved_os, resolved_arch = inspection.split("|")
    except ValueError:
        fail(f"unexpected inspect response: {inspection!r}")
    if not digest.startswith("sha256:"):
        fail(f"registry returned an unexpected digest: {digest!r}")
    if resolved_os != args.os or resolved_arch != args.arch:
        fail(
            f"resolved platform {resolved_os}/{resolved_arch}, expected "
            f"{args.os}/{args.arch}"
        )

    print(f"image={image}")
    print(f"tag={tag}")
    print(f"digest={digest}")
    print(f"platform={resolved_os}/{resolved_arch}")
    print(f"reference={reference}@{digest}")


if __name__ == "__main__":
    main()
