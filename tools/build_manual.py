# SPDX-License-Identifier: Apache-2.0
"""Stage and verify the existing manual, without importing native Gazebo."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts/docs-source'
SITE = ROOT / 'artifacts/manual'
REPO = 'https://github.com/Living-Proof-Labs/livingproof-sim-gazebo'


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = set()
        self.links = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        for key in ('href', 'src'):
            if key in attrs:
                self.links.append(attrs[key])


def check_site():
    pages = {p.resolve(): Page(p.read_text()) for p in SITE.rglob('*.html')}
    for path, page in pages.items():
        text = path.read_text()
        if 'assets/brand.css' not in text or 'data-md-color-primary="indigo"' in text:
            raise SystemExit(f'Missing shared brand or stock palette: {path}')
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc or link.startswith('/'):
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if target.is_dir():
                target /= 'index.html'
            if not target.exists():
                raise SystemExit(f'Broken local link: {path.name}: {link}')
            if url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids:
                raise SystemExit(f'Broken fragment: {path.name}: {link}')
    print(f'Checked brand, local links and fragments in {len(pages)} HTML pages')


def main():
    lock = json.loads((ROOT / 'docs-brand.lock.json').read_text())
    url = f"https://raw.githubusercontent.com/{lock['repository']}/{lock['commit']}/{lock['path']}"
    with urlopen(url, timeout=30) as response:
        brand = response.read()
    digest = hashlib.sha256(brand).hexdigest()
    if digest != lock['sha256']:
        raise SystemExit(f"Brand digest mismatch: expected {lock['sha256']}, got {digest}")
    shutil.rmtree(SOURCE, ignore_errors=True)
    shutil.copytree(ROOT / 'docs', SOURCE)
    (SOURCE / 'assets').mkdir(exist_ok=True)
    (SOURCE / 'assets/brand.css').write_bytes(brand)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    identity = {'repository': REPO, 'commit': commit, 'dirty': dirty, 'brand': lock}
    (SOURCE / 'build.json').write_text(json.dumps(identity, indent=2) + '\n')
    (SOURCE / 'version.md').write_text(
        '# Version and source\n\n'
        f'Docs: development · [{commit[:12]}]({REPO}/tree/{commit}).\n\n'
        f'Full source revision: `{commit}`. Working tree modified: `{dirty}`.\n\n'
        'This manual describes the checked-out development source, not a stable package release.\n'
        'Supported native context: Ubuntu 24.04 amd64, Gazebo Harmonic / Sim 8.\n\n'
        f'[Machine-readable identity](build.json) · [Source tags]({REPO}/tags).\n\n'
        'Historical rendered manuals are not maintained; use source tags for earlier revisions.\n'
        'Package provenance and native engine versions are reported by `livingproof-sim-gazebo --version`.\n\n'
        '[Verification scope](verification.md) · [Contribute, help and license](contribute.md).\n'
    )
    subprocess.run(['zensical', 'build', '--clean'], cwd=ROOT, check=True)
    check_site()


if __name__ == '__main__':
    main()
