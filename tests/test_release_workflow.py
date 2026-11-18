# SPDX-License-Identifier: Apache-2.0
"""Verify release workflow gating, draft assembly, and immutable publication order."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/verify.yml"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def test_release_job_gates_on_verification_and_main_push_only():
    workflow = _load_workflow()
    release = workflow["jobs"]["release"]
    assert set(release["needs"]) == {"verify", "publish-tests"}
    assert (
        release["if"]
        == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )
    assert release["permissions"] == {"contents": "write"}
    assert release["uses"].startswith(
        "Living-Proof-Labs/collaboration-guidelines/.github/workflows/semantic-release.yml@v"
    )
    assert release["with"] == {"draft-release": True}


def test_assemble_job_requires_draft_and_publishes_after_asset_upload():
    workflow = _load_workflow()
    assemble = workflow["jobs"]["assemble"]
    assert assemble["needs"] == "release"
    assert assemble["if"] == "needs.release.outputs.draft-created == 'true'"
    assert assemble["permissions"] == {"contents": "write"}

    steps = assemble["steps"]
    checkout = steps[0]
    assert checkout["with"]["ref"] == "${{ needs.release.outputs.git-tag }}"

    commands = [step.get("run", "") for step in steps]
    joined = "\n".join(commands)
    assert "task setup" in joined
    assert "task verify" in joined
    assert "task package" in joined
    assert "task smoke" in joined
    assert "sha256sum *.whl *.tar.gz > SHA256SUMS" in joined

    upload_idx = next(i for i, c in enumerate(commands) if "gh release upload" in c)
    publish_idx = next(
        i
        for i, c in enumerate(commands)
        if "gh release edit" in c and "--draft=false" in c
    )
    verify_idx = next(
        i
        for i, c in enumerate(commands)
        if "sha256sum -c SHA256SUMS" in c and "curl" in c
    )
    assert upload_idx < publish_idx < verify_idx
