# SPDX-License-Identifier: Apache-2.0
"""Fail closed before accepting an immutable release manual for Pages."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def validate(release, tag, version, sha):
    if not re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', tag):
        raise ValueError('Expected a stable vX.Y.Z release tag')
    if tag != f'v{version}' or release.get('tag_name') != tag:
        raise ValueError('Release tag/version mismatch')
    if (release.get('draft') is not False or release.get('prerelease') is not False
            or release.get('immutable') is not True or not release.get('published_at')
            or type(release.get('id')) is not int or release['id'] <= 0):
        raise ValueError('Expected an existing published immutable stable release')
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Expected the exact tested source SHA')
    if git('rev-parse', 'HEAD') != sha or git('rev-parse', f'refs/tags/{tag}^{{commit}}') != sha:
        raise ValueError('Release tag, checkout and tested source must match')
    if git('status', '--porcelain'):
        raise ValueError('Release manuals require a clean source tree')
    return {'channel': 'stable', 'version': version, 'tag': tag,
            'release_id': release['id'], 'immutable': True}


def hashes(site):
    files = sorted(site.rglob('*'))
    if any(p.is_symlink() for p in files):
        raise ValueError('Manual must not contain symlinks')
    result = {p.relative_to(site).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in files if p.is_file()}
    if not {'index.html', 'build.json', 'version.html'} <= result.keys():
        raise ValueError('Manual is missing required pages or provenance')
    return result


def accept(release, tag, version, sha):
    expected = validate(release, tag, version, sha)
    site = ROOT / 'artifacts/manual'
    identity = json.loads((site / 'build.json').read_text())
    if any(identity.get(k) != v for k, v in expected.items()):
        raise ValueError('Manual release identity mismatch')
    if identity.get('commit') != sha or identity.get('dirty') is not False:
        raise ValueError('Manual tested source mismatch')
    recorded = json.loads((ROOT / 'artifacts/manual-sha256.json').read_text())
    if recorded != hashes(site):
        raise ValueError('Manual bytes changed after checks')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate', 'accept'])
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--sha', required=True)
    args = parser.parse_args()
    operation = validate if args.command == 'validate' else accept
    operation(json.loads(args.release.read_text()), args.tag, args.version, args.sha)


if __name__ == '__main__':
    main()
