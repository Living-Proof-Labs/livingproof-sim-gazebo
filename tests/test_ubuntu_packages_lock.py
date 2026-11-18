# SPDX-License-Identifier: Apache-2.0
"""Every apt pin in the Ubuntu package lock is still in the live Noble indexes.

Ubuntu drops superseded versions from -updates and -security, which broke the
clean development image in #23. Offline: the lock is well-formed and the Mesa
set shares one version. LIVINGPROOF_NETWORK=1: each lock pin, and the five
Dockerfile apt pins, is present in noble, noble-updates, noble-security or the
OSRF gazebo-stable noble index (amd64, https only).
"""

from __future__ import annotations

import gzip
import os
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "tools/ubuntu-packages.lock"
DOCKERFILE = ROOT / "Dockerfile"
MESA = (
    "libegl-mesa0",
    "libgbm1",
    "libgl1-mesa-dri",
    "libglx-mesa0",
    "mesa-libgallium",
    "mesa-va-drivers",
    "mesa-vdpau-drivers",
    "mesa-vulkan-drivers",
)
SUITES = ("noble", "noble-updates", "noble-security")
COMPONENTS = ("main", "universe", "restricted", "multiverse")
ARCHIVE = "https://archive.ubuntu.com/ubuntu/dists"
OSRF = (
    "https://packages.osrfoundation.org/gazebo/ubuntu-stable/dists/noble/"
    "main/binary-amd64/Packages.gz"
)
DOCKERFILE_PINS = re.compile(
    r"(ca-certificates|curl|git-man|git|liberror-perl)=(\S+?)(?:;|\s|$)"
)
network = pytest.mark.skipif(
    not os.environ.get("LIVINGPROOF_NETWORK"), reason="set LIVINGPROOF_NETWORK=1"
)


def _pins(path: Path) -> list[tuple[str, str]]:
    pins = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, version = line.split("=", 1)
        pins.append((name, version))
    return pins


def _base(name: str) -> str:
    return name.split(":", 1)[0]


def test_the_lock_is_well_formed_and_the_mesa_set_shares_one_version():
    pins = _pins(LOCK)
    names = [name for name, _ in pins]
    assert pins and all(version for _, version in pins)
    assert len(names) == len(set(names))
    mesa = {name: version for name, version in pins if _base(name) in MESA}
    assert {_base(name) for name in mesa} == set(MESA)
    assert len(set(mesa.values())) == 1


def test_dockerfile_apt_pins_are_listed_or_are_the_five_bootstrap_packages():
    text = DOCKERFILE.read_text()
    found = dict(DOCKERFILE_PINS.findall(text))
    assert set(found) == {"ca-certificates", "curl", "git", "git-man", "liberror-perl"}
    lock = {_base(name): version for name, version in _pins(LOCK)}
    # The bootstrap pins may be installed before the lock; they must still be exact.
    assert all(version for version in found.values())
    # git and git-man are installed after the lock; ca-certificates and curl are
    # also in the lock when the lock carries them.
    for name in ("ca-certificates", "curl"):
        if name in lock:
            assert lock[name] == found[name], name


def _fetch_packages(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read()
    if url.endswith(".gz"):
        payload = gzip.decompress(payload)
    return payload.decode("utf-8", "replace")


def _index_versions(text: str) -> dict[str, set[str]]:
    versions: dict[str, set[str]] = defaultdict(set)
    name = version = arch = None
    for line in text.splitlines():
        if line.startswith("Package:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
        elif line.startswith("Architecture:"):
            arch = line.split(":", 1)[1].strip()
        elif line == "":
            if name and version:
                versions[name].add(version)
                if arch:
                    versions[f"{name}:{arch}"].add(version)
            name = version = arch = None
    return versions


@network
def test_every_lock_and_dockerfile_pin_is_in_the_live_noble_or_osrf_index():
    versions: dict[str, set[str]] = defaultdict(set)
    urls = [
        f"{ARCHIVE}/{suite}/{component}/binary-amd64/Packages.gz"
        for suite in SUITES
        for component in COMPONENTS
    ] + [OSRF]
    for url in urls:
        for key, found in _index_versions(_fetch_packages(url)).items():
            versions[key].update(found)
    missing = []
    for name, version in _pins(LOCK):
        have = versions.get(name) or versions.get(_base(name), set())
        if version not in have:
            missing.append(f"{name}={version}")
    text = DOCKERFILE.read_text()
    for name, version in DOCKERFILE_PINS.findall(text):
        have = versions.get(name) or versions.get(f"{name}:amd64", set())
        if version not in have:
            missing.append(f"Dockerfile {name}={version}")
    assert missing == [], (
        f"{len(missing)} pin(s) missing from the live indexes: " + ", ".join(missing)
    )
