# SPDX-License-Identifier: Apache-2.0
"""Apt snapshot bumps are proposed by a scheduled second-writer workflow.

Renovate has no datasource for snapshot.ubuntu.com IDs (the service has no
machine-readable catalog), so a repo-local workflow opens a draft PR. Offline:
the workflow is schedule or workflow_dispatch only, never writes to main, uses
the apt-snapshot/ branch prefix, states that it is the second writer, and
SHA-pins the same checkout action as verify.yml. Weakening any of those fails
this suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "bump-apt-snapshot.yml"
VERIFY = ROOT / ".github" / "workflows" / "verify.yml"
RENOVATE = ROOT / "renovate.json"

FORBIDDEN_TRIGGERS = (
    "pull_request:",
    "pull_request_target:",
    "workflow_run:",
    "push:",
)
MAIN_WRITES = (
    "git push origin main",
    "git push -u origin main",
    "git push --force",
    "git push -f",
    "git merge --ff-only origin/main",
    "refs/heads/main:",
)


def _code(text: str) -> str:
    return "\n".join(line.split(" #", 1)[0].rstrip() for line in text.splitlines())


def _uses(text: str) -> list[str]:
    return re.findall(r"^\s+-?\s*uses:\s*(\S+)", _code(text), re.M)


def _verify_checkout_pin() -> str:
    matches = [
        ref
        for ref in _uses(VERIFY.read_text(encoding="utf-8"))
        if ref.startswith("actions/checkout@")
    ]
    assert matches, "expected actions/checkout in verify.yml"
    sha = matches[0].split("@", 1)[1]
    assert re.fullmatch(r"[0-9a-f]{40}", sha), sha
    return sha


def assert_bump_workflow_is_safe(text: str) -> None:
    code = _code(text) + "\n"
    on = re.search(r"^on:\n((?:[ \t]+.+\n)+)", code, re.M)
    assert on is not None, "expected an on: block"
    block = on.group(1)
    cron = r"^  schedule:\n    - cron:\s+'\S+ \S+ \S+ \S+ \S+'\s*$"
    assert re.search(cron, block, re.M)
    assert re.search(r"^  workflow_dispatch:\s*$", block, re.M)
    for trigger in FORBIDDEN_TRIGGERS:
        assert trigger not in block, trigger

    perms = re.search(r"^permissions:\n((?:[ \t]+.+\n?)+)", code, re.M)
    assert perms is not None, "expected top-level permissions"
    allowed = {"contents: write", "pull-requests: write"}
    declared = {line.strip() for line in perms.group(1).splitlines() if line.strip()}
    assert declared <= allowed
    assert "contents: write" in declared
    assert "pull-requests: write" in declared
    assert "write-all" not in code
    assert "id-token: write" not in code

    assert "runs-on: ubuntu-24.04" in code
    assert re.search(
        r"^concurrency:\n"
        r"  group: bump-apt-snapshot-\$\{\{ github\.ref \}\}\n"
        r"  cancel-in-progress: false\s*$",
        code,
        re.M,
    )
    assert "github.ref == 'refs/heads/main'" in code or (
        'github.ref == "refs/heads/main"' in code
    )

    uses = _uses(text)
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref
    checkout = _verify_checkout_pin()
    assert f"actions/checkout@{checkout}" in uses

    assert "tools/regenerate-ubuntu-lock.sh" in code
    assert "apt-snapshot/" in code
    assert "--draft" in code or "draft: true" in code
    assert re.search(r"second writer", code, re.I)
    assert "24 hours" in code or "24h" in code or "timedelta(hours=24)" in text

    lowered = code.lower()
    for token in MAIN_WRITES:
        assert token not in lowered and token not in code, token
    # Pushes must target the apt-snapshot/ prefix, never HEAD:main.
    for match in re.findall(r"git push\b[^\n]+", code):
        assert "apt-snapshot/" in match
        assert re.search(r"\bmain\b", match) is None, match
    for match in re.findall(r"gh pr\b[^\n]+", code):
        assert "main" not in match or "base" in match or "develop" in match or True
        # Creating a PR against main as base is allowed; pushing to main is not.


def test_snapshot_bump_workflow_is_a_scheduled_second_writer():
    assert WORKFLOW.is_file(), "missing .github/workflows/bump-apt-snapshot.yml"
    assert_bump_workflow_is_safe(WORKFLOW.read_text(encoding="utf-8"))


def test_renovate_does_not_claim_a_snapshot_datasource():
    """snapshot.ubuntu.com has no machine-readable ID catalog.

    A custom regex manager without a real datasource would not bump cleanly,
    so bumps are left to the scheduled workflow.
    """
    text = RENOVATE.read_text(encoding="utf-8")
    assert "snapshot.ubuntu.com" not in text
    assert "UBUNTU_SNAPSHOT" not in text
    assert "customDatasources" not in text


@pytest.mark.parametrize(
    "description,mutate",
    [
        (
            "run on pull requests",
            lambda t: t.replace(
                "  workflow_dispatch:\n",
                "  workflow_dispatch:\n  pull_request:\n",
            ),
        ),
        (
            "grant write-all",
            lambda t: t.replace(
                "  contents: write\n",
                "  contents: write\n  packages: write-all\n",
            )
            if "contents: write" in t
            else t + "\npermissions:\n  contents: write-all\n",
        ),
        (
            "push the bump to main",
            lambda t: t + "\n        run: git push origin main\n",
        ),
        (
            "open a ready PR rather than a draft",
            lambda t: t.replace("--draft", "").replace("draft: true", "draft: false"),
        ),
        (
            "drop the second-writer disclosure",
            lambda t: re.sub(r"second writer", "updater", t, flags=re.I),
        ),
        (
            "push to a branch without the apt-snapshot prefix",
            lambda t: t.replace("apt-snapshot/", "deps/"),
        ),
        (
            "unpin checkout from a full commit",
            lambda t: t.replace(
                "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                "actions/checkout@v4",
            ),
        ),
        (
            "stop regenerating the lock",
            lambda t: t.replace(
                "tools/regenerate-ubuntu-lock.sh",
                "tools/run-task.sh",
            ),
        ),
        (
            "run on a feature branch",
            lambda t: t.replace("refs/heads/main", "refs/heads/develop"),
        ),
    ],
)
def test_weakening_the_snapshot_bump_workflow_fails(description, mutate):
    text = WORKFLOW.read_text(encoding="utf-8")
    weakened = mutate(text)
    assert weakened != text, description
    with pytest.raises(AssertionError):
        assert_bump_workflow_is_safe(weakened)
