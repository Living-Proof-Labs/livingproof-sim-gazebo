# SPDX-License-Identifier: Apache-2.0
"""Dockerfile base images are pinned to a tag plus a multi-architecture index digest.

Vera review of #14. Offline: every ``FROM`` names ``image:tag@sha256:<64 hex>``.
LIVINGPROOF_NETWORK=1: the Docker Hub ``ubuntu`` digest is an OCI image index (not a
single-platform manifest) that includes linux/amd64, the platform the Gazebo apt
source here supports. The digest itself is not frozen, so later Renovate digest bumps
still pass, and old digests stay resolvable after the tag moves.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

import pytest

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
FROM = re.compile(
    r"^FROM\s+(?P<image>[\w./-]+):(?P<tag>[\w.-]+)@sha256:(?P<digest>[0-9a-f]{64})(?:\s+AS\s+\S+)?$",
    re.MULTILINE,
)
INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)


def _froms() -> list[re.Match[str]]:
    return list(FROM.finditer(DOCKERFILE.read_text()))


def test_every_base_image_is_tag_and_digest_pinned():
    lines = [
        line for line in DOCKERFILE.read_text().splitlines() if line.startswith("FROM ")
    ]
    assert lines
    assert len(_froms()) == len(lines), lines
    assert any(m["image"] == "ubuntu" and m["tag"] == "24.04" for m in _froms())


@pytest.mark.skipif(
    not os.environ.get("LIVINGPROOF_NETWORK"), reason="set LIVINGPROOF_NETWORK=1"
)
def test_ubuntu_digest_is_a_multi_arch_index_with_amd64():
    (pin,) = [m for m in _froms() if m["image"] == "ubuntu"]
    scope = "repository:library/ubuntu:pull"
    token_url = f"https://auth.docker.io/token?service=registry.docker.io&scope={scope}"
    with urllib.request.urlopen(token_url, timeout=30) as response:
        token = json.load(response)["token"]
    request = urllib.request.Request(
        f"https://registry-1.docker.io/v2/library/ubuntu/manifests/sha256:{pin['digest']}",
        headers={"Authorization": f"Bearer {token}", "Accept": ", ".join(INDEX_TYPES)},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.headers["Docker-Content-Digest"] == f"sha256:{pin['digest']}"
        assert response.headers["Content-Type"].split(";")[0] in INDEX_TYPES
        index = json.load(response)
    platforms = {
        (m["platform"]["os"], m["platform"]["architecture"])
        for m in index["manifests"]
        if m.get("platform", {}).get("os") != "unknown"
    }
    assert ("linux", "amd64") in platforms
    assert len(platforms) > 1
