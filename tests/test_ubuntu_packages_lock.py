# SPDX-License-Identifier: Apache-2.0
"""Every apt pin in the Ubuntu package lock is still in the live Noble indexes.

Ubuntu drops superseded versions from -updates and -security, which broke the
clean development image in #23. After #37 the daily check is an early warning
of how far the pinned snapshot lags the live archive, and still the monitor
for OSRF pins. Offline: the lock is well-formed and the Mesa set shares one
version; recorded OSRF metadata guards dependencies and digest coverage.
LIVINGPROOF_NETWORK=1: each lock pin, and the Dockerfile git-layer
apt pins, is present in noble, noble-updates, noble-security or the OSRF
gazebo-stable noble index (amd64, https only). Recorded OSRF SHA256 values
must also match the live index for the same package version. This monitors
hashes daily; it does not enforce the recorded hashes at install time.
"""

from __future__ import annotations

import gzip
import json
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
TRANSPORT = re.compile(r"gz-transport13(?:-|:|$)")
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
        name, rest = line.split("=", 1)
        version = rest.split()[0]
        pins.append((name, version))
    return pins


def _osrf_sha256s(path: Path) -> dict[str, str]:
    """Return name -> sha256 for lock pins that record a digest."""
    found = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, rest = line.split("=", 1)
        parts = rest.split()
        digest = next(
            (p.split(":", 1)[1] for p in parts[1:] if p.startswith("sha256:")), None
        )
        if digest is not None:
            found[name] = digest
    return found


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


def test_the_osrf_transport13_set_shares_one_version_and_records_digests():
    """The nine Transport 13 packages are one release, each with a digest.

    OSRF removed 13.6.0-1~noble from the live index (#46); a half-updated set
    would fail to install with unmet versioned dependencies.
    """
    pins = [(name, version) for name, version in _pins(LOCK) if TRANSPORT.search(name)]
    assert len(pins) == 9, pins
    assert len({version for _, version in pins}) == 1
    digests = _osrf_sha256s(LOCK)
    for name, _ in pins:
        assert re.fullmatch(r"[0-9a-f]{64}", digests.get(name, "")), name


def test_dockerfile_apt_pins_are_listed_or_are_the_git_layer_and_lock_packages():
    """ca-certificates is unpinned only for the live-archive bootstrap.

    The locked install and the later git layer stay exact. curl is in the lock
    so it is installed from the snapshot, not from the live archive.
    """
    text = DOCKERFILE.read_text()
    found = dict(DOCKERFILE_PINS.findall(text))
    assert set(found) == {"git", "git-man", "liberror-perl"}
    assert all(version for version in found.values())
    lock = {_base(name): version for name, version in _pins(LOCK)}
    assert "ca-certificates" in lock
    assert "curl" in lock
    # The bootstrap install of ca-certificates must not carry a version pin.
    assert re.search(
        r"apt-get\b[^\n]*install -y ca-certificates(?:\s|;|\\|$)",
        text,
    ), "bootstrap ca-certificates must be unpinned"
    assert not re.search(
        r"apt-get\b[^\n]*install -y ca-certificates=",
        text,
    )


def _fetch_packages(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read()
    if url.endswith(".gz"):
        payload = gzip.decompress(payload)
    return payload.decode("utf-8", "replace")


def _index_versions(text: str) -> dict[str, set[str]]:
    versions: dict[str, set[str]] = defaultdict(set)
    name = version = arch = None
    for line in (text + "\n\n").splitlines():
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


def _check_osrf_sha256s(text: str, lock: Path) -> None:
    hashes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for stanza in text.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in stanza.splitlines() if ": " in line
        )
        name, version = fields.get("Package"), fields.get("Version")
        if not name or not version:
            continue
        digest = fields.get("SHA256", "<missing>")
        hashes[name, version].add(digest)
        if arch := fields.get("Architecture"):
            hashes[f"{name}:{arch}", version].add(digest)
    expected = _osrf_sha256s(lock)
    mismatches = []
    for name, version in _pins(lock):
        if name not in expected:
            continue
        found = hashes.get((name, version), set())
        if found != {expected[name]}:
            mismatches.append(
                f"{name}={version}: expected {expected[name]}, "
                f"found {', '.join(sorted(found)) or '<missing package/version>'}"
            )
    assert not mismatches, "OSRF SHA256 mismatch: " + "; ".join(mismatches)


@network
def test_every_lock_and_dockerfile_pin_is_in_the_live_noble_or_osrf_index():
    versions: dict[str, set[str]] = defaultdict(set)
    for suite in SUITES:
        for component in COMPONENTS:
            url = f"{ARCHIVE}/{suite}/{component}/binary-amd64/Packages.gz"
            for key, found in _index_versions(_fetch_packages(url)).items():
                versions[key].update(found)
    osrf = _fetch_packages(OSRF)
    _check_digest_coverage(osrf, versions, LOCK)
    _check_osrf_sha256s(osrf, LOCK)
    _check_exact_dependencies(osrf, LOCK)
    for key, found in _index_versions(osrf).items():
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


def _stanzas(text: str) -> list[dict[str, str]]:
    """Read Debian control fields, including continuation lines."""
    records = []
    fields: dict[str, str] = {}
    key = ""
    for line in (text + "\n\n").splitlines():
        if not line:
            if fields:
                records.append(fields)
            fields = {}
            key = ""
        elif line[0].isspace() and key:
            fields[key] += " " + line.strip()
        else:
            key, value = line.split(":", 1)
            fields[key] = value.strip()
    return records


def _check_exact_dependencies(text: str, lock: Path) -> None:
    """Require each exact dependency, including an absent lock entry.

    This is deliberately not an apt solver. Fail explicitly on exact-version
    alternative groups rather than silently ignoring unsupported constraints.
    """
    pins = dict(_pins(lock))
    locked = {_base(name): version for name, version in pins.items()}
    records = _stanzas(text)
    osrf_names = {r["Package"] for r in records}
    selected = [
        r
        for r in records
        if r.get("Architecture") in {"amd64", "all"}
        and locked.get(r["Package"]) == r["Version"]
    ]
    available = {r["Package"] for r in selected}
    errors = [
        f"{name}={version}: missing OSRF package/version metadata"
        for name, version in locked.items()
        if name in osrf_names and name not in available
    ]
    for record in selected:
        for field in ("Depends", "Pre-Depends"):
            for dep in record.get(field, "").split(","):
                if not re.search(r"\(\s*=", dep):
                    continue
                match = re.fullmatch(r"\s*([^\s(|]+)\s*\(=\s*([^)]+)\)\s*", dep)
                if not match:
                    errors.append(
                        f"{record['Package']}: unsupported exact dependency {dep}"
                    )
                    continue
                name, version = match.groups()
                found = pins.get(name) if ":" in name else locked.get(name)
                if found != version.strip():
                    errors.append(
                        f"{record['Package']}: requires {dep.strip()}, "
                        f"locked {found or '<missing>'}"
                    )
    assert not errors, "OSRF exact dependencies: " + "; ".join(errors)


def _check_digest_coverage(osrf: str, ubuntu: dict[str, set[str]], lock: Path) -> None:
    # A removed version still needs its digest. Presence and hash checks report
    # the unavailable version separately; a missing digest must not hide it.
    versions = _index_versions(osrf)
    digests = _osrf_sha256s(lock)
    missing = [
        f"{name}={version}"
        for name, version in _pins(lock)
        if name in versions
        and version not in ubuntu.get(name, set())
        and not re.fullmatch(r"[0-9a-f]{64}", digests.get(name, ""))
    ]
    assert not missing, "OSRF-only pins without a recorded sha256: " + ", ".join(
        missing
    )


def _recorded_osrf_index() -> str:
    records = json.loads(
        (ROOT / "tests/fixtures/osrf-locked-packages.json").read_text()
    )
    names = {record["Package"] for record in records}
    missing = {_base(name) for name in _osrf_sha256s(LOCK)} - names
    assert not missing, f"Refresh recorded OSRF metadata for: {sorted(missing)}"
    return "\n\n".join(
        "\n".join(f"{key}: {value}" for key, value in record.items())
        for record in records
    )


def test_locked_osrf_exact_dependencies_match_recorded_index():
    _check_exact_dependencies(_recorded_osrf_index(), LOCK)


def test_recorded_osrf_only_pins_have_digests():
    # Conservatively require hashes for every recorded OSRF package name.
    # The live monitor additionally allows an exact version available in Ubuntu.
    _check_digest_coverage(_recorded_osrf_index(), {}, LOCK)
