# SPDX-License-Identifier: Apache-2.0
"""Pinned GitHub Pages action SHAs must name the published tags those SHAs resolve to.

The SHAs are pinned; comments that name only a moving major tag (v3, v4) can drift
from the commit they describe. Offline: each Pages action pin is a 40-character SHA
with a full vX.Y.Z tag comment. LIVINGPROOF_NETWORK=1: that SHA is the peeled commit
of the commented tag. The exact SHA and tag are not frozen, so a later bump still
passes when the comment and the commit stay in agreement.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "verify.yml"

PAGES_ACTIONS = (
    "actions/upload-pages-artifact",
    "actions/deploy-pages",
)

USES = re.compile(
    r"uses:\s+(?P<action>actions/(?:upload-pages-artifact|deploy-pages))"
    r"@(?P<sha>[0-9a-f]{40})\s+#\s+(?P<tag>v\d+\.\d+\.\d+)"
)


def _pins() -> list[tuple[str, str, str]]:
    found = [
        (match.group("action"), match.group("sha"), match.group("tag"))
        for match in USES.finditer(WORKFLOW.read_text())
    ]
    return found


def _peeled_tag_commit(action: str, tag: str) -> str:
    listing = subprocess.check_output(
        [
            "git",
            "ls-remote",
            "--tags",
            f"https://github.com/{action}.git",
            f"refs/tags/{tag}",
        ],
        text=True,
        timeout=30,
    )
    peeled = None
    direct = None
    for line in listing.splitlines():
        sha, ref = line.split("\t", 1)
        if ref.endswith("^{}"):
            peeled = sha
        else:
            direct = sha
    assert peeled or direct, listing
    return peeled or direct


def test_pages_action_pins_name_a_full_release_tag():
    found = _pins()
    names = [action for action, _sha, _tag in found]
    assert list(names) == list(PAGES_ACTIONS)
    for action, sha, tag in found:
        assert re.fullmatch(r"[0-9a-f]{40}", sha), (action, sha)
        assert re.fullmatch(r"v\d+\.\d+\.\d+", tag), (action, tag)


@pytest.mark.skipif(
    not os.environ.get("LIVINGPROOF_NETWORK"), reason="set LIVINGPROOF_NETWORK=1"
)
def test_pages_action_shas_match_the_commented_tags():
    found = _pins()
    assert found, "expected Pages action pins in verify.yml"
    for action, sha, tag in found:
        assert sha == _peeled_tag_commit(action, tag), (action, tag, sha)
