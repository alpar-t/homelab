#!/usr/bin/env python3
"""Pin verified images in the official Argo CD install or rollback manifest."""

import argparse
import hashlib
from pathlib import Path


VERSIONS = {
    'v3.4.12': {
        'source_sha256': '56ee644081c84aa380952e477adc11f59decc8c2574296380ce2a1f8e0512623',
        'argocd_digest': 'da43096503915aa78980da13ffaad832247b90821744cd9ce8bdce8e43bded71',
    },
    'v3.4.4': {
        'source_sha256': 'b0f9119821f2e19b852c842b9cb235eb9c3ef1549554fbda6aa5904e8d440eae',
        'argocd_digest': '2fb3efa9eaa42382acb39c9a1485eaac7a1ad7a09e8aa7da7143ca256fa6da09',
    },
}


def prepare(source: Path, destination: Path, version: str) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError('source and destination must differ')
    original = source.read_bytes()
    if hashlib.sha256(original).hexdigest() != VERSIONS[version]['source_sha256']:
        raise ValueError('official manifest checksum differs from the reviewed version')
    manifest = original.decode('utf-8')
    replacements = {
        f'image: quay.io/argoproj/argocd:{version}': (
            f'image: quay.io/argoproj/argocd:{version}@sha256:'
            f'{VERSIONS[version]["argocd_digest"]}', 8),
        'image: ghcr.io/dexidp/dex:v2.45.0': (
            'image: ghcr.io/dexidp/dex:v2.45.0@sha256:'
            'b8469881d3cb3a73001506f0d3aaefecb9c45d2311c1e0f405d8ac538316c59d', 1),
        'image: public.ecr.aws/docker/library/redis:8.2.3-alpine': (
            'image: public.ecr.aws/docker/library/redis:8.2.3-alpine@sha256:'
            '08ad0b1d280850169a790dba1393ff7a90aef951fc19632cf4d3ce4f78e679ba', 1),
    }
    for unpinned, (pinned, expected) in replacements.items():
        if manifest.count(unpinned) != expected:
            raise ValueError(f'unexpected image count: {unpinned}')
        manifest = manifest.replace(unpinned, pinned)
    destination.write_text(manifest)
    print(f'{destination}: sha256:{hashlib.sha256(destination.read_bytes()).hexdigest()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', choices=VERSIONS)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    prepare(args.source, args.destination, args.version)
