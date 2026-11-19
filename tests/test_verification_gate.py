# SPDX-License-Identifier: Apache-2.0
"""Execute the actual aggregate script with failed, skipped and missing evidence."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _workflow():
    return yaml.safe_load((ROOT / ".github/workflows/verify.yml").read_text())


def _run(needs, event="merge_group", fork="false"):
    script = _workflow()["jobs"]["verification-gate"]["steps"][0]["run"]
    return subprocess.run(
        ["bash", "-c", script],
        env={
            **os.environ,
            "NEEDS_JSON": json.dumps(needs),
            "GITHUB_EVENT_NAME": event,
            "IS_FORK": fork,
        },
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def _evidence(publisher="success"):
    return {"verify": {"result": "success"}, "publish-tests": {"result": publisher}}


def test_gate_always_runs_for_pr_and_queue_without_path_filters():
    workflow = _workflow()
    events = workflow["on"] if "on" in workflow else workflow[True]
    assert events["pull_request"] is None
    assert events["merge_group"] == {"types": ["checks_requested"]}
    gate = workflow["jobs"]["verification-gate"]
    assert gate["name"] == "Gazebo verification gate"
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == set(workflow["jobs"]) - {
        "verification-gate",
        "deploy-docs",
    }
    assert gate["permissions"] == {}
    env = gate["steps"][0]["env"]
    assert env["NEEDS_JSON"] == "${{ toJSON(needs) }}"
    assert env["IS_FORK"] == (
        "${{ github.event_name == 'pull_request' && "
        "github.event.pull_request.head.repo.full_name != github.repository }}"
    )


@pytest.mark.parametrize("event", ["pull_request", "merge_group", "push"])
def test_complete_evidence_passes(event):
    assert _run(_evidence(), event) == 0


@pytest.mark.parametrize("job", ["verify", "publish-tests"])
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "neutral", None])
def test_incomplete_evidence_fails(job, result):
    needs = _evidence()
    needs[job]["result"] = result
    assert _run(needs) != 0


def test_only_external_pull_request_can_skip_publisher():
    assert _run(_evidence("skipped"), "pull_request", "true") == 0
    for event in ["merge_group", "push"]:
        assert _run(_evidence("skipped"), event, "true") != 0
    assert _run(_evidence("skipped"), "pull_request", "false") != 0
    needs = _evidence("skipped")
    needs["verify"]["result"] = "failure"
    assert _run(needs, "pull_request", "true") != 0


def test_missing_extra_jobs_and_unknown_event_fail():
    assert _run({"verify": {"result": "success"}}) != 0
    assert _run({**_evidence(), "extra": {"result": "success"}}) != 0
    assert _run(_evidence(), "workflow_dispatch") != 0
