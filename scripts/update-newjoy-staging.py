#!/usr/bin/env python3
"""Select a verified immutable website build and update staging only."""
import pathlib
import re
import subprocess

IMAGE = 'ghcr.io/alpar-t/newjoy-website'
TAG_PATTERN = r'sha-[0-9a-f]{40}-run-([0-9]+)-([0-9]+)'
TARGET = pathlib.Path('config/newjoy-website-staging/manifests/deployment.yaml')


def order(tag):
    match = re.fullmatch(TAG_PATTERN, tag)
    if not match:
        raise ValueError('unexpected website release tag')
    return tuple(map(int, match.groups()))


def replace_image(manifest, reference):
    pattern = r'(\s+image: )(' + re.escape(IMAGE) + r':[^\s]+)'
    found = re.findall(pattern, manifest)
    if len(found) != 1:
        raise ValueError('expected exactly one staging website image')
    if not re.fullmatch(re.escape(IMAGE) + ':' + TAG_PATTERN + r'@sha256:[0-9a-f]{64}', reference):
        raise ValueError('expected verified immutable website reference')
    old = found[0][1]
    old_tag = old.split(':', 1)[1].split('@', 1)[0]
    new_tag = reference.split(':', 1)[1].split('@', 1)[0]
    if re.fullmatch(TAG_PATTERN, old_tag) and order(old_tag) >= order(new_tag):
        return manifest
    return re.sub(pattern, lambda m: m[1] + reference, manifest)


def main():
    resolver = ['scripts/resolve-container-image.py', IMAGE]
    listing = subprocess.run(resolver + ['--list', '--tag-pattern', TAG_PATTERN, '--limit', '0'], text=True, capture_output=True)
    if listing.returncode:
        # No releases before the first real three-hour observation window is normal.
        if 'no matching version-like tags' in listing.stderr:
            print('No live website release yet; staging unchanged.')
            return
        raise RuntimeError('registry tag lookup failed')
    tags = listing.stdout.splitlines()
    tag = max(tags, key=order)
    resolved = subprocess.check_output(resolver + [tag], text=True)
    values = dict(line.split('=', 1) for line in resolved.splitlines())
    if values.get('platform') != 'linux/amd64':
        raise ValueError('unexpected platform')
    before = TARGET.read_text()
    after = replace_image(before, values['reference'])
    if before != after:
        TARGET.write_text(after)
        print('Staging candidate: ' + values['reference'])
    else:
        print('Staging already references this or a newer release.')


if __name__ == '__main__':
    main()
