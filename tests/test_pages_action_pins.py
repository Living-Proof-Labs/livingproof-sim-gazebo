# SPDX-License-Identifier: Apache-2.0
"""Pinned GitHub Pages action SHAs must name the published tags those SHAs resolve to.

The SHAs were already pinned; comments that name only a moving major tag (v3, v4) can drift
from the commit they describe. This freezes each comment to the published tag for that SHA.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "verify.yml"

# Published tags, peeled to the commits already pinned in verify.yml.
EXPECTED = {
    "actions/upload-pages-artifact": (
        "56afc609e74202658d3ffba0e8f6dda462b719fa",
        "v3.0.1",
    ),
    "actions/deploy-pages": (
        "d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e",
        "v4.0.5",
    ),
}

USES = re.compile(
    r"uses:\s+(?P<action>actions/(?:upload-pages-artifact|deploy-pages))"
    r"@(?P<sha>[0-9a-f]{40})\s+#\s+(?P<tag>v\d+\.\d+\.\d+)"
)


def test_pages_action_pins_name_the_published_tags():
    text = WORKFLOW.read_text()
    found = {
        m.group("action"): (m.group("sha"), m.group("tag")) for m in USES.finditer(text)
    }
    assert found == EXPECTED
