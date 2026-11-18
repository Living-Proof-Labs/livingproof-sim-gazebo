# SPDX-License-Identifier: Apache-2.0
"""Behavioural evidence for release gating, draft assembly, and recovery.

Offline: these tests read the real workflow and evaluate its job conditions
the way GitHub would for the expressions this workflow uses. Nothing here
publishes a release. A pull-request run of the verification workflow is hosted
evidence that a PR does not release. The hosted "no releasable commits" decision and
a successful publish (criterion 4's last path), plus a clean install of the
first published wheel, can only be proven by runs on main after merge.
"""

from __future__ import annotations

import copy
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/release.yml"
README = ROOT / "README.md"
STATUS_FUNCTIONS = re.compile(r"\b(always|failure|cancelled|success)\(")


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


def test_sha_guard_commands_accept_a_matching_tag_and_reject_mismatches(tmp_path):
    """Execute the assemble SHA guard, not only assert its text is in the workflow.

    Matching HEAD + tag + GITHUB_SHA must pass. A wrong GITHUB_SHA, a tag on a
    different commit, or an unknown tag must fail closed.
    """
    guard = next(
        step
        for step in _load_workflow()["jobs"]["assemble"]["steps"]
        if step.get("name") == "Require the release tag to name the verified commit"
    )
    assert "if" not in guard and not guard.get("continue-on-error", False)
    commands = guard["run"]
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in commands
    assert 'test "$(git rev-parse "$RELEASE_TAG^{commit}")" = "$GITHUB_SHA"' in commands
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["init"], check=True, capture_output=True)
    subprocess.run(
        git + ["config", "user.email", "vera@livingprooflabs.invalid"], check=True
    )
    subprocess.run(git + ["config", "user.name", "Vera (verification)"], check=True)
    (repo / "f").write_text("one\n")
    subprocess.run(git + ["add", "f"], check=True)
    subprocess.run(git + ["commit", "-m", "feat: one"], check=True, capture_output=True)
    tagged = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    subprocess.run(git + ["tag", "v1.0.0"], check=True)
    subprocess.run(git + ["tag", "-a", "v1.0.1", "-m", "annotated"], check=True)
    (repo / "f").write_text("two\n")
    subprocess.run(git + ["add", "f"], check=True)
    subprocess.run(git + ["commit", "-m", "feat: two"], check=True, capture_output=True)
    later = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()

    def run_guard(*, ref: str, sha: str, tag: str) -> int:
        subprocess.run(
            git + ["checkout", "--quiet", ref], check=True, capture_output=True
        )
        env = {**os.environ, "GITHUB_SHA": sha, "RELEASE_TAG": tag}
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", commands],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        ).returncode

    assert run_guard(ref="v1.0.0", sha=tagged, tag="v1.0.0") == 0
    assert run_guard(ref="v1.0.1", sha=tagged, tag="v1.0.1") == 0
    assert run_guard(ref="v1.0.0", sha=later, tag="v1.0.0") != 0
    assert run_guard(ref=later, sha=later, tag="v1.0.0") != 0
    assert run_guard(ref=later, sha=tagged, tag="v1.0.0") != 0
    assert (
        run_guard(
            ref="v1.0.0", sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", tag="v1.0.0"
        )
        != 0
    )
    assert run_guard(ref="v1.0.0", sha=tagged, tag="v9.9.9") != 0


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


def _release_context(**overrides):
    context = {
        "github.event.workflow_run.conclusion": "success",
        "github.event.workflow_run.event": "push",
        "github.event.workflow_run.head_branch": "main",
        "github.event.workflow_run.head_repository.full_name": "owner/repo",
        "github.repository": "owner/repo",
        "github.event.workflow_run.head_sha": "a" * 40,
        "github.sha": "a" * 40,
    }
    context.update(overrides)
    return context


def _release_allowed(context):
    # Parse the actual YAML expression; fail on unsupported syntax instead of
    # substituting a separately maintained copy of the gate.
    expression = _load_workflow()["jobs"]["release"]["if"]
    decisions = []
    for term in expression.split("&&"):
        left, right = term.strip().split(" == ")
        expected = right[1:-1] if right.startswith("'") else context[right]
        decisions.append(context[left] == expected)
    return all(decisions)


def test_release_accepts_only_successful_same_repository_main_push():
    assert _release_allowed(_release_context())
    for field, values in {
        "conclusion": ["failure", "cancelled", "skipped", "neutral", ""],
        "event": [
            "pull_request",
            "pull_request_target",
            "workflow_dispatch",
            "schedule",
        ],
        "head_branch": ["topic", "", "refs/heads/main"],
        "head_repository.full_name": ["attacker/fork", ""],
        "head_sha": ["b" * 40, ""],
    }.items():
        for value in values:
            context = _release_context(**{f"github.event.workflow_run.{field}": value})
            assert not _release_allowed(context), (field, value)


def test_main_moving_requires_verification_of_the_new_revision():
    # A passed, B is newer main when workflow_run is emitted: no release of B.
    assert not _release_allowed(_release_context(**{"github.sha": "b" * 40}))
    # B subsequently passes: the new completion event can release B.
    assert _release_allowed(
        _release_context(
            **{
                "github.sha": "b" * 40,
                "github.event.workflow_run.head_sha": "b" * 40,
            }
        )
    )
    # Main moving after the event does not mutate github.sha. The pinned shared
    # workflow checks out that event revision and its action asserts HEAD == SHA.
    # Assembly independently rejects any tag naming a newer/unverified revision.


def test_release_trigger_permissions_and_pinned_engine():
    workflow = _load_workflow()
    assert workflow[True] == {
        "workflow_run": {
            "workflows": ["Gazebo verification"],
            "types": ["completed"],
            "branches": ["main"],
        }
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    release = workflow["jobs"]["release"]
    assert release["permissions"] == {"contents": "write"}
    assert release["uses"] == (
        "Living-Proof-Labs/collaboration-guidelines/.github/workflows/semantic-release.yml@v9.6.14"
    )
    assert release["with"] == {"draft-release": True}
    verification = yaml.safe_load((ROOT / ".github/workflows/verify.yml").read_text())
    assert verification["name"] == "Gazebo verification"
    assert "release" not in verification["jobs"]
    assert "assemble" not in verification["jobs"]
    assert verification["jobs"]["publish-tests"]["needs"] == "verify"


def test_assembly_guard_precedes_any_build_or_publication():
    steps = _load_workflow()["jobs"]["assemble"]["steps"]
    guard_index = next(
        i
        for i, step in enumerate(steps)
        if step.get("name") == "Require the release tag to name the verified commit"
    )
    assert (
        guard_index == 1
    )  # immediately after checkout, before executing repository code
    assert not _load_workflow()["jobs"]["assemble"].get("continue-on-error", False)


@pytest.mark.parametrize(
    "field",
    [
        "conclusion",
        "event",
        "head_branch",
        "head_repository.full_name",
        "head_sha",
    ],
)
def test_removing_each_release_gate_is_detected(monkeypatch, field):
    workflow = copy.deepcopy(_load_workflow())
    workflow["jobs"]["release"]["if"] = " && ".join(
        term
        for term in workflow["jobs"]["release"]["if"].split("&&")
        if f"github.event.workflow_run.{field} " not in term
    )
    monkeypatch.setattr(__import__(__name__), "_load_workflow", lambda: workflow)
    with pytest.raises(AssertionError):
        test_release_accepts_only_successful_same_repository_main_push()


@pytest.mark.parametrize(
    "mutation", ["bypass", "mask-errors", "conditional", "continue"]
)
def test_bypassing_the_actual_assembly_guard_is_detected(
    monkeypatch, tmp_path, mutation
):
    workflow = copy.deepcopy(_load_workflow())
    guard = workflow["jobs"]["assemble"]["steps"][1]
    if mutation == "bypass":
        guard["run"] = "exit 0\n" + guard["run"]
    elif mutation == "mask-errors":
        guard["run"] = "\n".join(
            line + " || true" for line in guard["run"].splitlines()
        )
    elif mutation == "conditional":
        guard["if"] = "false"
    else:
        guard["continue-on-error"] = True
    monkeypatch.setattr(__import__(__name__), "_load_workflow", lambda: workflow)
    with pytest.raises(AssertionError):
        test_sha_guard_commands_accept_a_matching_tag_and_reject_mismatches(tmp_path)
