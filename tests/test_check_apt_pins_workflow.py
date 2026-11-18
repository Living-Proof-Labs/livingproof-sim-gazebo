# SPDX-License-Identifier: Apache-2.0
"""The daily apt-pins workflow stays a scheduled, read-only live-index check.

Offline: check-apt-pins.yml runs only on a daily cron and workflow_dispatch,
is contents:read, SHA-pins the same checkout and upload-artifact commits as
verify.yml, sets LIVINGPROOF_NETWORK=1, and does not write to the repo or
open issues or pull requests. Weakening any of those fails this suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "check-apt-pins.yml"
VERIFY = ROOT / ".github" / "workflows" / "verify.yml"
PYPROJECT = ROOT / "pyproject.toml"

WRITE_TOKENS = (
    "contents: write",
    "issues: write",
    "pull-requests: write",
    "id-token: write",
    "packages: write",
    "write-all",
    "permissions: write-all",
)
FORBIDDEN_TRIGGERS = (
    "pull_request:",
    "pull_request_target:",
    "workflow_run:",
    "push:",
)
FORBIDDEN_ACTIONS = (
    "git push",
    "gh issue",
    "gh pr",
    "peter-evans/",
    "softprops/action-gh-release",
    "secrets.",
)


def _code(text: str) -> str:
    return "\n".join(line.split(" #", 1)[0].rstrip() for line in text.splitlines())


def _uses(text: str) -> list[str]:
    return re.findall(r"^\s+-?\s*uses:\s*(\S+)", _code(text), re.M)


def _verify_pin(action: str) -> str:
    matches = [
        ref
        for ref in _uses(VERIFY.read_text(encoding="utf-8"))
        if ref.startswith(f"{action}@")
    ]
    assert matches, f"expected {action} in verify.yml"
    sha = matches[0].split("@", 1)[1]
    assert re.fullmatch(r"[0-9a-f]{40}", sha), (action, sha)
    return sha


def _pytest_pin() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r"pytest==(\d+\.\d+\.\d+)", text)
    assert match, "expected a pytest== pin in pyproject.toml"
    return match.group(1)


def assert_workflow_is_safe(text: str) -> None:
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
    assert perms is not None and perms.group(1).strip() == "contents: read"
    assert len(re.findall(r"^\s*permissions\s*:", code, re.M)) == 1
    for token in WRITE_TOKENS:
        assert token not in code, token

    assert re.search(
        r"^concurrency:\n"
        r"  group: check-apt-pins-\$\{\{ github\.ref \}\}\n"
        r"  cancel-in-progress: false\s*$",
        code,
        re.M,
    )
    assert "persist-credentials: false" in code
    assert "runs-on: ubuntu-24.04" in code

    uses = _uses(text)
    assert uses, "expected pinned actions"
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref
    checkout_sha = _verify_pin("actions/checkout")
    upload_sha = _verify_pin("actions/upload-artifact")
    assert f"actions/checkout@{checkout_sha}" in uses
    assert f"actions/upload-artifact@{upload_sha}" in uses

    assert re.search(r"^\s+LIVINGPROOF_NETWORK:\s+'1'\s*$", code, re.M)
    assert "tests/test_ubuntu_packages_lock.py" in code
    pytest_ver = _pytest_pin()
    assert f"pytest=={pytest_ver}" in code

    lowered = code.lower()
    for token in FORBIDDEN_ACTIONS:
        assert token not in code and token not in lowered, token
    assert "GITHUB_TOKEN" not in code


def test_daily_apt_pins_workflow_is_a_read_only_scheduled_check():
    assert WORKFLOW.is_file()
    assert_workflow_is_safe(WORKFLOW.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "description,mutate",
    [
        (
            "drop the network env so the live-index test is skipped",
            lambda t: t.replace("LIVINGPROOF_NETWORK: '1'", "LIVINGPROOF_NETWORK: '0'"),
        ),
        (
            "grant contents write",
            lambda t: t.replace("contents: read", "contents: write"),
        ),
        (
            "unpin checkout from a full commit",
            lambda t: t.replace(
                "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                "actions/checkout@v4",
            ),
        ),
        (
            "run on pull requests",
            lambda t: t.replace(
                "  workflow_dispatch:\n",
                "  workflow_dispatch:\n  pull_request:\n",
            ),
        ),
        (
            "leave credentials in the checkout",
            lambda t: t.replace("          persist-credentials: false\n", ""),
        ),
        (
            "stop running the lock-vs-live-index test",
            lambda t: t.replace(
                "tests/test_ubuntu_packages_lock.py",
                "tests/test_pages_action_pins.py",
            ),
        ),
        (
            "open an issue on drift",
            lambda t: t + "\n        run: gh issue create --title drift\n",
        ),
    ],
)
def test_weakening_the_daily_apt_pins_workflow_fails(description, mutate):
    text = WORKFLOW.read_text(encoding="utf-8")
    weakened = mutate(text)
    assert weakened != text, description
    with pytest.raises(AssertionError):
        assert_workflow_is_safe(weakened)
