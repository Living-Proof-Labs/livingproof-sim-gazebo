# SPDX-License-Identifier: Apache-2.0
"""Release manual acceptance executes against disposable real Git repositories."""

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "manual_release", ROOT / "tools/manual_release.py"
)
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)


@pytest.fixture
def released(tmp_path, monkeypatch):
    monkeypatch.setattr(manual, "ROOT", tmp_path)

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(tmp_path), *args], text=True
        ).strip()

    git("init", "-q")
    git("config", "user.name", "Local test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / ".gitignore").write_text("artifacts/\n")
    git("add", ".")
    git("commit", "-qm", "test: source")
    sha = git("rev-parse", "HEAD")
    git("tag", "-a", "v1.2.3", "-m", "release")
    release = {
        "id": 123,
        "tag_name": "v1.2.3",
        "draft": False,
        "prerelease": False,
        "immutable": True,
        "published_at": "2026-11-22T00:00:00Z",
    }
    return tmp_path, git, release, sha


def test_release_and_delivery_retry_do_not_change_tags(released):
    _, git, release, sha = released
    before = git("show-ref", "--tags")
    for _ in range(2):
        identity = manual.validate(release, "v1.2.3", "1.2.3", sha)
        assert identity["channel"] == "stable"
    assert git("show-ref", "--tags") == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("draft", True),
        ("prerelease", True),
        ("immutable", False),
        ("immutable", None),
        ("published_at", ""),
        ("id", None),
        ("tag_name", "v1.2.4"),
    ],
)
def test_unpublished_mutable_or_mismatched_release_fails(released, field, value):
    _, _, release, sha = released
    release[field] = value
    with pytest.raises(ValueError):
        manual.validate(release, "v1.2.3", "1.2.3", sha)


def test_missing_release_version_tag_and_wrong_source_fail(released):
    root, git, release, sha = released
    for payload, tag, version, source in [
        ({}, "v1.2.3", "1.2.3", sha),
        (release, "v1.2.3", "1.2.4", sha),
        (release, "v1.2.3", "1.2.3", "a" * 40),
        ({**release, "tag_name": "v1.2.4"}, "v1.2.4", "1.2.4", sha),
    ]:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            manual.validate(payload, tag, version, source)
    (root / "untracked").write_text("dirty")
    with pytest.raises(ValueError, match="clean"):
        manual.validate(release, "v1.2.3", "1.2.3", sha)
    git("add", ".")
    git("commit", "-qm", "test: newer source")
    with pytest.raises(ValueError, match="must match"):
        manual.validate(release, "v1.2.3", "1.2.3", git("rev-parse", "HEAD"))


def test_acceptance_rejects_preview_wrong_identity_and_changed_bytes(released):
    root, _, release, sha = released
    site = root / "artifacts/manual"
    (site / "version").mkdir(parents=True)
    (site / "index.html").write_text("manual")
    (site / "version.html").write_text("v1.2.3")
    identity = {
        **manual.validate(release, "v1.2.3", "1.2.3", sha),
        "commit": sha,
        "dirty": False,
    }

    def record(value):
        (site / "build.json").write_text(json.dumps(value))
        (root / "artifacts/manual-sha256.json").write_text(
            json.dumps(manual.hashes(site))
        )

    record(identity)
    manual.accept(release, "v1.2.3", "1.2.3", sha)
    manual.accept(release, "v1.2.3", "1.2.3", sha)
    for mutation in [
        {"channel": "development"},
        {"version": "1.2.4"},
        {"commit": "b" * 40},
        {"dirty": True},
    ]:
        record({**identity, **mutation})
        with pytest.raises(ValueError):
            manual.accept(release, "v1.2.3", "1.2.3", sha)
    record(identity)
    (site / "index.html").write_text("changed after checks")
    with pytest.raises(ValueError, match="bytes changed"):
        manual.accept(release, "v1.2.3", "1.2.3", sha)


def test_workflow_keeps_preview_native_tests_and_package_publication_separate():
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    verify = yaml.safe_load((ROOT / ".github/workflows/verify.yml").read_text())
    build = release["jobs"]["build-manual"]
    assert build["needs"] == ["release", "assemble"]
    assert (
        build["if"]
        == "needs.release.outputs.draft-created == 'true' && needs.assemble.result == 'success'"
    )
    assert build["permissions"] == {"contents": "read"}
    commands = "\n".join(s.get("run", "") for s in build["steps"])
    assert (
        commands.index("manual_release.py validate")
        < commands.index("task docs -- --release")
        < commands.index("manual_release.py accept")
    )
    assert "/releases/tags/$RELEASE_TAG" in commands
    deploy = release["jobs"]["deploy-docs"]
    assert deploy["needs"] == ["release", "build-manual"]
    assert not any("checkout@" in s.get("uses", "") for s in deploy["steps"])
    upload = next(s for s in build["steps"] if s.get("id") == "pages")
    assert upload["with"]["name"] == "${{ steps.pages-name.outputs.name }}"
    assert (
        deploy["steps"][-1]["with"]["artifact_name"]
        == "${{ needs.build-manual.outputs.artifact-name }}"
    )
    assert build["outputs"]["artifact-id"] == "${{ steps.pages.outputs.artifact-id }}"
    preview = verify["jobs"]["verify"]
    for task in ["setup", "verify", "docs", "package", "smoke"]:
        assert any(s.get("run") == f"task {task}" for s in preview["steps"])
    assert "pages: write" not in (ROOT / ".github/workflows/verify.yml").read_text()
    assert all(
        "task docs" not in s.get("run", "")
        for s in release["jobs"]["assemble"]["steps"]
    )
