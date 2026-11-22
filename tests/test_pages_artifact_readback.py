# SPDX-License-Identifier: Apache-2.0
"""Exercise native artifact readback gates without contacting GitHub."""

import hashlib
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def jobs():
    return yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]


def test_native_routes_use_actual_upload_identity_and_one_retry_each():
    build, deploy = jobs()["build-manual"], jobs()["deploy-docs"]
    assert deploy["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
    steps = deploy["steps"]
    assert steps[-3]["name"] == "Require matching ID and name readback of the exact tar"
    assert steps[-2]["id"] == "freshness"
    assert steps[-1]["id"] == "deployment"
    assert steps[-1]["if"] == "steps.freshness.outputs.current == 'true'"
    assert build["outputs"]["artifact-id"] == "${{ steps.pages.outputs.artifact-id }}"
    assert (
        build["outputs"]["tar-sha256"] == "${{ steps.pages-name.outputs.tar-sha256 }}"
    )
    assert (
        steps[-3]["env"]["EXPECTED_TAR"]
        == "${{ needs.build-manual.outputs.tar-sha256 }}"
    )
    assert steps[-3]["env"]["EXPECTED_NAME"] == steps[-1]["with"]["artifact_name"]
    assert len([s for s in steps if "download-artifact@" in s.get("uses", "")]) == 4
    for route, selector in [("id", "artifact-ids"), ("name", "name")]:
        first = next(s for s in steps if s.get("id") == f"pages-{route}-first")
        retry = next(s for s in steps if s.get("id") == f"pages-{route}-retry")
        assert first["continue-on-error"] is True
        assert retry["if"] == f"steps.pages-{route}-first.outcome == 'failure'"
        assert "continue-on-error" not in retry
        assert (
            first["uses"]
            == retry["uses"]
            == "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093"
        )
        for step in [first, retry]:
            # Omitting github-token/repository/run-id selects the native runtime service.
            assert set(step["with"]) == {selector, "path"}
            assert (
                step["with"][selector]
                == "${{ needs.build-manual.outputs.artifact-" + route + " }}"
            )
        assert first["with"]["path"] != retry["with"]["path"]
        assert steps[steps.index(retry) - 1]["run"] == "sleep 4"
        assert steps[steps.index(retry) - 1]["if"] == retry["if"]
        source = steps[-3]["env"][route.upper() + "_READBACK"]
        assert f"steps.pages-{route}-first.outcome == 'success'" in source
        assert f"steps.pages-{route}-retry.outputs.download-path" in source
    text = (ROOT / ".github/workflows/release.yml").read_text()
    assert "/actions/artifacts/" not in text
    assert "group: gazebo-release" in text
    assert "cancel-in-progress: false" in text


@pytest.mark.parametrize(
    "kind",
    [
        "exact",
        "missing-id",
        "missing-name",
        "wrong-id",
        "wrong-name",
        "wrong-attempt",
        "missing-digest",
        "missing-id-path",
        "missing-name-path",
    ],
)
def test_downloaded_tar_bytes_must_both_match(tmp_path, kind):
    identifier, named = tmp_path / "id", tmp_path / "name"
    expected_name = "github-pages-v1.2.3-source-123-2"
    id_location = identifier / (
        "older-attempt" if kind == "wrong-attempt" else expected_name
    )
    id_location.mkdir(parents=True)
    named.mkdir()
    if kind != "missing-id":
        (id_location / "artifact.tar").write_bytes(
            b"wrong" if kind == "wrong-id" else b"sealed"
        )
    if kind != "missing-name":
        (named / "artifact.tar").write_bytes(
            b"wrong" if kind == "wrong-name" else b"sealed"
        )
    step = jobs()["deploy-docs"]["steps"][-3]
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={
            **os.environ,
            "EXPECTED_TAR": ""
            if kind == "missing-digest"
            else hashlib.sha256(b"sealed").hexdigest(),
            "EXPECTED_NAME": expected_name,
            "ID_READBACK": "" if kind == "missing-id-path" else str(identifier),
            "NAME_READBACK": "" if kind == "missing-name-path" else str(named),
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == (kind == "exact"), result.stderr


@pytest.mark.parametrize(
    "identifier,valid",
    [("123", True), ("", False), ("0", False), ("1,2", False), ("abc", False)],
)
def test_missing_upload_id_cannot_select_unrelated_artifacts(identifier, valid):
    step = next(
        s
        for s in jobs()["deploy-docs"]["steps"]
        if s.get("name") == "Require a valid Pages artifact ID"
    )
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]], env={**os.environ, "UPLOADED_ID": identifier}
    )
    assert (result.returncode == 0) == valid


def test_archive_emits_the_digest_of_actual_tar(tmp_path):
    site = tmp_path / "artifacts/manual"
    site.mkdir(parents=True)
    (site / "index.html").write_text("accepted site")
    step = next(
        s for s in jobs()["build-manual"]["steps"] if s.get("id") == "pages-name"
    )
    output = tmp_path / "output"
    subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=tmp_path,
        check=True,
        env={
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
            "RELEASE_TAG": "v1.2.3",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "2",
        },
    )
    digest = hashlib.sha256((tmp_path / "artifact.tar").read_bytes()).hexdigest()
    assert (
        output.read_text()
        == f"name=github-pages-v1.2.3-{'a' * 40}-123-2\ntar-sha256={digest}\n"
    )
