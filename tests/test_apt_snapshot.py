# SPDX-License-Identifier: Apache-2.0
"""The Gazebo development image installs Ubuntu packages from one dated snapshot.

Implements #37. Offline tests check the Dockerfile, lock, pin file, ID guards
and documentation. LIVINGPROOF_NETWORK=1 additionally hash-checks the pinned
ubuntu:24.04 amd64 layer and checks the recorded image created date against
the registry. This is build-environment pinning, not a robot capability result.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_ubuntu_packages_lock import _osrf_sha256s, _pins

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
LOCK = ROOT / "tools/ubuntu-packages.lock"
PIN = ROOT / "tools/ubuntu-snapshot.pin"
CHECK_ID = ROOT / "tools/check-snapshot-id.sh"
REGENERATE = ROOT / "tools/regenerate-ubuntu-lock.sh"
DOCS = ROOT / "docs/verification.md"
SNAPSHOT_RE = re.compile(r"^20\d{6}T\d{6}Z$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
CREATED_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
EXTRAS = (
    "less",
    "libcbor0.10",
    "libfido2-1",
    "libxmuu1",
    "openssh-client",
    "patch",
    "xauth",
)
SUITES = ("noble", "noble-updates", "noble-backports", "noble-security")
network = pytest.mark.skipif(
    not os.environ.get("LIVINGPROOF_NETWORK"), reason="set LIVINGPROOF_NETWORK=1"
)


def _pin_file() -> dict[str, str]:
    values: dict[str, str] = {}
    text = PIN.read_text() if PIN.is_file() else ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name] = value
    return values


def _lock_header() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in LOCK.read_text().splitlines():
        if not line.startswith("#"):
            break
        if "Ubuntu snapshot:" in line:
            values["UBUNTU_SNAPSHOT"] = line.split(":", 1)[1].strip()
        elif "Base image:" in line:
            values["UBUNTU_IMAGE"] = line.split(":", 1)[1].strip()
        elif "amd64 layer:" in line:
            values["UBUNTU_AMD64_LAYER"] = line.split(":", 1)[1].strip()
        elif "Image created:" in line:
            values["UBUNTU_IMAGE_CREATED"] = line.split(":", 1)[1].strip()
    return values


def _dockerfile() -> str:
    return DOCKERFILE.read_text()


def _snapshot_from_dockerfile(text: str) -> str:
    match = re.search(r"^ARG UBUNTU_SNAPSHOT=([0-9A-TZ]+)\s*$", text, re.M)
    assert match, "Dockerfile must declare ARG UBUNTU_SNAPSHOT"
    return match.group(1)


def test_the_pin_file_names_a_past_snapshot_and_the_ubuntu_layer():
    values = _pin_file()
    assert set(values) >= {
        "UBUNTU_SNAPSHOT",
        "UBUNTU_IMAGE_DIGEST",
        "UBUNTU_IMAGE_CREATED",
        "UBUNTU_AMD64_MANIFEST",
        "UBUNTU_AMD64_LAYER",
    }
    assert SNAPSHOT_RE.fullmatch(values["UBUNTU_SNAPSHOT"])
    when = datetime.strptime(values["UBUNTU_SNAPSHOT"], "%Y%m%dT%H%M%SZ").replace(
        tzinfo=timezone.utc
    )
    assert when < datetime.now(timezone.utc), values["UBUNTU_SNAPSHOT"]
    created = values["UBUNTU_IMAGE_CREATED"]
    assert CREATED_RE.fullmatch(created)
    assert when >= datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    ), "snapshot ID is older than the base image"
    assert values["UBUNTU_IMAGE_DIGEST"].startswith("sha256:")
    assert DIGEST_RE.fullmatch(values["UBUNTU_IMAGE_DIGEST"])
    assert DIGEST_RE.fullmatch(values["UBUNTU_AMD64_MANIFEST"])
    assert DIGEST_RE.fullmatch(values["UBUNTU_AMD64_LAYER"])


def test_dockerfile_and_lock_agree_with_the_pin_file():
    values = _pin_file()
    text = _dockerfile()
    assert _snapshot_from_dockerfile(text) == values["UBUNTU_SNAPSHOT"]
    from_line = re.search(r"^FROM ubuntu:24\.04@(sha256:[0-9a-f]{64})", text, re.M)
    assert from_line, "Dockerfile must pin ubuntu:24.04 by digest"
    assert from_line.group(1) == values["UBUNTU_IMAGE_DIGEST"]
    header = _lock_header()
    assert header["UBUNTU_SNAPSHOT"] == values["UBUNTU_SNAPSHOT"]
    assert values["UBUNTU_IMAGE_DIGEST"] in header["UBUNTU_IMAGE"]
    assert header["UBUNTU_AMD64_LAYER"] == values["UBUNTU_AMD64_LAYER"]
    assert header["UBUNTU_IMAGE_CREATED"] == values["UBUNTU_IMAGE_CREATED"]


def test_dockerfile_installs_ubuntu_packages_from_the_snapshot():
    text = _dockerfile()
    snapshot = _snapshot_from_dockerfile(text)
    assert "https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT}/" in text or (
        f"https://snapshot.ubuntu.com/ubuntu/{snapshot}/" in text
    )
    assert "http://snapshot.ubuntu.com" not in text
    for suite in SUITES:
        assert re.search(rf"\b{suite}\b", text), suite
    assert "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg" in text
    # Verification must stay on: no trusted=yes, no disabled checks.
    lowered = text.lower()
    assert "trusted: yes" not in lowered
    assert "[trusted=yes]" not in lowered
    assert "acquire::https::verify-peer=false" not in lowered
    assert "acquire::check-valid-until=false" not in lowered
    assert "check-valid-until=no" not in lowered


def test_lock_install_uses_no_install_recommends_and_omits_unused_extras():
    text = _dockerfile()
    assert re.search(
        r"xargs -a /tmp/ubuntu-packages.lock apt-get\b[^\n]*"
        r"--no-install-recommends",
        text,
    ), "locked install must pass --no-install-recommends"
    lock_names = {_base_name(name) for name, _ in _pins(LOCK)}
    unexpected = [name for name in EXTRAS if name in lock_names]
    assert unexpected == [], (
        "these Recommends extras are unused by the image and must not be "
        f"locked unless a need is recorded: {unexpected}"
    )


def _base_name(name: str) -> str:
    return name.split(":", 1)[0]


def test_live_archive_ca_certificates_bootstrap_is_logged_and_documented():
    text = _dockerfile()
    docs = DOCS.read_text() if DOCS.is_file() else ""
    assert "--mount=type=secret,id=ca,required=false" in text
    assert "dpkg-query" in text and "ca-certificates" in text
    assert re.search(r"unpinned live-archive ca-certificates", text) or re.search(
        r"ca-certificates:", text
    )
    combined = text + "\n" + docs
    assert "one unpinned package" in combined.lower() or (
        "unpinned" in combined.lower() and "ca-certificates" in combined
    )
    assert "https-only" in combined.lower() or "https only" in combined.lower()
    assert "ISRG" not in text
    certs = list(ROOT.glob("**/*ISRG*")) + list(ROOT.glob("**/*isrg*"))
    assert certs == [], f"ISRG root must not be vendored: {certs}"
    assert re.search(r"not a robot capability result", docs, re.I)


def test_the_ca_secret_path_still_works_with_and_without_the_secret():
    text = _dockerfile()
    assert "if [ -f /run/secrets/ca ]; then" in text
    assert "SSL_CERT_FILE=/run/secrets/ca" in text
    assert (
        'Acquire::https::CaInfo="${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}"'
        in text
    )
    # The snapshot host is https whether or not the secret is present; without
    # the secret the just-installed bundle is the CA path.
    assert "snapshot.ubuntu.com" in text
    compose = (ROOT / "compose.yaml").read_text()
    runner = (ROOT / "tools/run-task.sh").read_text()
    assert "id: ca" in compose or "- ca" in compose
    assert "ca.pem" in runner


def test_osrf_pins_record_sha256_and_are_not_on_the_ubuntu_snapshot():
    pins = _pins(LOCK)
    digests = _osrf_sha256s(LOCK)
    assert len(digests) >= 120, "expected the OSRF pin set to record sha256"
    for name, digest in digests.items():
        assert re.fullmatch(r"[0-9a-f]{64}", digest), (name, digest)
    # Ubuntu pins must not be required to carry a digest; OSRF pins must.
    assert set(digests) <= {name for name, _ in pins}


def test_drift_check_still_uses_the_live_archive_and_osrf():
    source = (ROOT / "tests/test_ubuntu_packages_lock.py").read_text()
    assert "https://archive.ubuntu.com/ubuntu/dists" in source
    assert "packages.osrfoundation.org/gazebo/ubuntu-stable" in source
    assert "snapshot.ubuntu.com" not in source
    workflow = (ROOT / ".github/workflows/check-apt-pins.yml").read_text()
    assert "tests/test_ubuntu_packages_lock.py" in workflow


def test_check_snapshot_id_rejects_a_future_id_and_an_id_before_the_image(tmp_path):
    assert CHECK_ID.is_file(), "tools/check-snapshot-id.sh is missing"
    result = subprocess.run(
        ["bash", str(CHECK_ID), "20990101T000000Z", "2026-11-10T08:36:35Z"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "not in the past" in result.stderr
    result = subprocess.run(
        ["bash", str(CHECK_ID), "20261101T000000Z", "2026-11-10T08:36:35Z"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "older than the base image" in result.stderr
    result = subprocess.run(
        ["bash", str(CHECK_ID), "20261118T000000Z", "2026-11-10T08:36:35Z"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    # The Dockerfile must run this check before any snapshot network call.
    text = _dockerfile()
    assert "check-snapshot-id.sh" in text
    assert "UBUNTU_SNAPSHOT" in text
    assert "UBUNTU_IMAGE_CREATED" in text


def test_regenerate_script_fails_closed_and_uses_no_install_recommends():
    assert REGENERATE.is_file(), "tools/regenerate-ubuntu-lock.sh is missing"
    text = REGENERATE.read_text()
    assert text.startswith("#!/usr/bin/env bash")
    parsed = subprocess.run(
        ["bash", "-n", str(REGENERATE)], capture_output=True, text=True
    )
    assert parsed.returncode == 0, parsed.stderr
    assert "--no-install-recommends" in text
    assert "sha256sum" in text or "hashlib" in text
    result = subprocess.run(
        ["bash", str(REGENERATE), "20990101T000000Z"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "not in the past" in result.stderr


def test_regenerate_script_treats_download_as_a_flag_not_a_workdir(tmp_path):
    result = subprocess.run(
        ["bash", str(REGENERATE), "20990101T000000Z", "--download"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "not in the past" in result.stderr
    assert not (tmp_path / "--download").exists()


@network
def test_recorded_ubuntu_layer_matches_the_registry_and_hashes():
    values = _pin_file()
    digest = values["UBUNTU_IMAGE_DIGEST"]
    token_url = (
        "https://auth.docker.io/token?service=registry.docker.io"
        "&scope=repository:library/ubuntu:pull"
    )
    with urllib.request.urlopen(token_url, timeout=30) as response:
        token = json.load(response)["token"]
    accept = (
        "application/vnd.oci.image.index.v1+json,"
        "application/vnd.docker.distribution.manifest.list.v2+json"
    )
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/library/ubuntu/manifests/{digest}",
        headers={"Authorization": f"Bearer {token}", "Accept": accept},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        index = json.load(response)
    amd64 = next(
        m["digest"]
        for m in index["manifests"]
        if m.get("platform", {}).get("os") == "linux"
        and m.get("platform", {}).get("architecture") == "amd64"
    )
    assert amd64 == values["UBUNTU_AMD64_MANIFEST"]
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/library/ubuntu/manifests/{amd64}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": (
                "application/vnd.oci.image.manifest.v1+json,"
                "application/vnd.docker.distribution.manifest.v2+json"
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        manifest = json.load(response)
    layer = manifest["layers"][0]["digest"]
    assert layer == values["UBUNTU_AMD64_LAYER"]
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/library/ubuntu/blobs/{manifest['config']['digest']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        created = json.load(response)["created"]
    assert created.startswith(values["UBUNTU_IMAGE_CREATED"][:-1])
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/library/ubuntu/blobs/{layer}",
        headers={"Authorization": f"Bearer {token}"},
    )
    hasher = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    assert f"sha256:{hasher.hexdigest()}" == values["UBUNTU_AMD64_LAYER"]
