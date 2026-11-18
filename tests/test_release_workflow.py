# SPDX-License-Identifier: Apache-2.0
"""Behavioural evidence for release gating, draft assembly, and recovery.

Offline: these tests read the real workflow and evaluate its job conditions
the way GitHub would for the expressions this workflow uses. Nothing here
publishes a release. A pull-request run of this workflow is hosted evidence
that a PR does not release. The hosted "no releasable commits" decision and
a successful publish (criterion 4's last path), plus a clean install of the
first published wheel, can only be proven by runs on main after merge.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/verify.yml"
README = ROOT / "README.md"
STATUS_FUNCTIONS = re.compile(r"\b(always|failure|cancelled|success)\(")

EVENTS = ("pull_request", "merge_group", "schedule", "workflow_dispatch", "push")
REFS = (
    "refs/heads/main",
    "refs/heads/topic",
    "refs/pull/1/merge",
    "refs/heads/gh-readonly-queue/main/pr-1-abc",
)


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text()


def _load_workflow() -> dict:
    return yaml.safe_load(_workflow_text())


def _job_block(text: str, job: str) -> str:
    match = re.search(rf"^  {re.escape(job)}:\s*$", text, re.MULTILINE)
    assert match, f"job {job} not found"
    after = text.index("\n", match.start()) + 1
    later = re.search(r"^  [A-Za-z0-9_-]+:\s*$", text[after:], re.MULTILINE)
    return text[match.start() : (after + later.start()) if later else len(text)]


def _scalar(block: str, key: str) -> str | None:
    match = re.search(rf"^    {re.escape(key)}:[ \t]*(.*)$", block, re.MULTILINE)
    return None if match is None else match.group(1).strip()


def _evaluate(expression: str, context: dict[str, str]) -> bool:
    # Evaluates only the expression shape this workflow may use: == and !=
    # against string literals, joined by && or ||.
    def value(term: str) -> bool:
        match = re.fullmatch(
            r"(github\.[a-z_]+|needs\.[a-z0-9_-]+\.outputs\.[a-z0-9_-]+)\s*(==|!=)\s*'([^']*)'",
            term.strip(),
        )
        assert match, f"unsupported condition term: {term}"
        equal = context[match.group(1)] == match.group(3)
        return equal if match.group(2) == "==" else not equal

    return any(
        all(value(term) for term in group.split("&&"))
        for group in expression.split("||")
    )


def _implicit_needs_succeeded(
    needed: list[str], results: dict[str, str], expression: str
) -> bool:
    if STATUS_FUNCTIONS.search(expression):
        return True
    return all(results.get(name) == "success" for name in needed)


def _needed(job: dict) -> list[str]:
    needs = job["needs"]
    if isinstance(needs, str):
        return [needs]
    return list(needs)


def _release_runs(event: str, ref: str, results: dict[str, str]) -> bool:
    job = _load_workflow()["jobs"]["release"]
    expression = job["if"]
    context = {"github.event_name": event, "github.ref": ref}
    return _evaluate(expression, context) and _implicit_needs_succeeded(
        _needed(job), results, expression
    )


def _assemble_runs(draft_created: str, release_result: str) -> bool:
    job = _load_workflow()["jobs"]["assemble"]
    expression = job["if"]
    context = {"needs.release.outputs.draft-created": draft_created}
    return _evaluate(expression, context) and _implicit_needs_succeeded(
        _needed(job), {"release": release_result}, expression
    )


def _assemble_commands() -> str:
    steps = _load_workflow()["jobs"]["assemble"]["steps"]
    return "\n".join(step.get("run", "") for step in steps)


def _successful_verification() -> dict[str, str]:
    return {"verify": "success", "publish-tests": "success"}


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


def test_only_a_push_to_main_with_successful_verification_runs_release():
    ok = _successful_verification()
    for event in EVENTS:
        for ref in REFS:
            expected = event == "push" and ref == "refs/heads/main"
            assert _release_runs(event, ref, ok) is expected, f"{event} {ref}"


def test_a_pull_request_run_does_not_release():
    ok = _successful_verification()
    for event in ("pull_request", "merge_group"):
        for ref in REFS:
            assert _release_runs(event, ref, ok) is False, f"{event} {ref}"
            assert _assemble_runs("true", "success") is True
    # Assemble never runs on a PR because it needs release, and release does not run.
    assert _assemble_runs("true", "skipped") is False
    on = _workflow_text()
    assert "pull_request_target" not in on.split("\npermissions:", 1)[0]


def test_a_failed_verification_blocks_the_release():
    release = _job_block(_workflow_text(), "release")
    assert STATUS_FUNCTIONS.search(_scalar(release, "if") or "") is None
    for job in ("verify", "publish-tests"):
        for result in ("failure", "cancelled", "skipped", "neutral"):
            results = _successful_verification()
            results[job] = result
            assert _release_runs("push", "refs/heads/main", results) is False, (
                f"{job}: {result}"
            )
        missing = {k: v for k, v in _successful_verification().items() if k != job}
        assert _release_runs("push", "refs/heads/main", missing) is False, (
            f"missing {job}"
        )
    assert _release_runs("push", "refs/heads/main", _successful_verification()) is True


def test_a_push_with_no_releasable_commits_does_not_assemble_or_publish():
    # The shared engine returns draft-created=false (and empty version/git-tag)
    # when there is no next release. Assemble is skipped, so nothing is published.
    # The engine's own decision is tested in collaboration-guidelines; this
    # checks the caller does not publish unless a draft was created.
    assert _assemble_runs("false", "success") is False
    assert _assemble_runs("", "success") is False
    assert _assemble_runs("true", "failure") is False
    assert _assemble_runs("true", "success") is True
    assemble = _job_block(_workflow_text(), "assemble")
    assert STATUS_FUNCTIONS.search(_scalar(assemble, "if") or "") is None
    assert _scalar(assemble, "if") == "needs.release.outputs.draft-created == 'true'"


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


def test_assemble_requires_the_tag_to_name_the_verified_commit():
    # Criterion 2: assets come from the verified run. Assemble rebuilds at the
    # tag because hatch-vcs versions from that tag, so it must first prove the
    # tag names the same commit verification just passed (GITHUB_SHA).
    commands = _assemble_commands()
    checkout_to_package = commands.split("task package", 1)[0]
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in checkout_to_package
    assert (
        'test "$(git rev-parse "$RELEASE_TAG^{commit}")" = "$GITHUB_SHA"'
        in checkout_to_package
    )


def test_every_release_upload_replaces_assets_so_a_rerun_can_finish_the_draft():
    uploads = [
        line
        for line in _assemble_commands().splitlines()
        if "gh release upload" in line
    ]
    assert uploads and all("--clobber" in line for line in uploads)


def test_assemble_does_not_retarget_or_create_tags():
    assemble = _job_block(_workflow_text(), "assemble")
    assert re.search(r"\bgit\s+tag\b", assemble) is None
    assert re.search(r"\bgit\s+push\b", assemble) is None
    assert re.search(r"git/refs", assemble) is None
    assert "gh release delete" not in assemble
    assert "--target" not in assemble


def test_readme_explains_rebuild_at_the_tag_and_assemble_failure_recovery():
    text = README.read_text()
    assert "hatch-vcs" in text
    assert "same commit" in text
    assert "unpublished" in text
    assert "Re-run the failed `assemble` job" in text
    assert "not retarget" in text or "do not retarget" in text
    assert (
        "will not recreate the draft" in text or "does not recreate the draft" in text
    )
