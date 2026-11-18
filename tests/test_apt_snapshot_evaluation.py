# SPDX-License-Identifier: Apache-2.0
"""The #26 apt-snapshot evaluation answers every question and states a verdict.

Evaluation only: the document must answer each of the seven questions in the
issue, name one allowed recommendation, give the dated snapshot it tested (a
past ID, because a future ID resolves to the moving latest archive), say it is not
a robot capability result, and ship the script that reproduces the lock test.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "evaluations/apt-snapshot.md"
SCRIPT = ROOT / "evaluations/apt-snapshot/resolve-lock.sh"
VERDICTS = (
    "adopt",
    "adopt with a defined OSRF plan",
    "reject in favour of an alternative",
)
QUESTIONS = {
    1: "retention and availability",
    2: "signature verification",
    3: "security and updates pockets",
    4: "OSRF",
    5: "monitoring-only alternative",
    6: "bump cadence and ownership",
    7: "collaboration-guidelines",
}


@pytest.fixture(scope="module")
def text() -> str:
    return EVALUATION.read_text() if EVALUATION.is_file() else ""


def test_the_evaluation_document_exists():
    assert EVALUATION.is_file(), "evaluations/apt-snapshot.md is missing"


def _sections(text: str) -> dict[int, str]:
    parts = re.split(r"^## Q(\d+)\b.*$", text, flags=re.MULTILINE)
    return {int(n): body for n, body in zip(parts[1::2], parts[2::2])}


def test_every_question_has_its_own_section_with_evidence(text):
    sections = _sections(text)
    assert sorted(sections) == sorted(QUESTIONS)
    for number, topic in QUESTIONS.items():
        body = sections[number]
        assert topic.lower() in text.lower(), topic
        assert len(body.split()) >= 40, f"Q{number} is not answered"


def test_exactly_one_allowed_recommendation_is_stated(text):
    found = re.findall(r"^\*\*Recommendation:\*\* (.+?)\.?$", text, flags=re.MULTILINE)
    assert len(found) == 1, found
    assert found[0] in VERDICTS


def test_the_tested_snapshot_is_a_past_id_not_a_moving_one(text):
    ids = set(re.findall(r"\b(20\d{6}T\d{6}Z)\b", text))
    assert ids, "no snapshot ID was recorded"
    now = datetime.now(timezone.utc)
    for snapshot in ids:
        when = datetime.strptime(snapshot, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
        assert when < now, f"{snapshot} is not in the past"
    assert "future" in text.lower(), "the moving-latest behaviour must be stated"


def test_it_is_not_described_as_a_robot_capability_result(text):
    assert re.search(r"not a robot capability result", text, flags=re.IGNORECASE)


def test_an_adopt_verdict_carries_a_drafted_implementation_issue(text):
    verdict = re.search(r"^\*\*Recommendation:\*\* (.+?)\.?$", text, re.MULTILINE)
    assert verdict
    if verdict.group(1).startswith("adopt"):
        assert re.search(r"^## Draft implementation issue", text, flags=re.MULTILINE)
        assert "Acceptance" in text


def test_the_reproduction_script_exists_and_parses():
    assert SCRIPT.is_file(), "evaluations/apt-snapshot/resolve-lock.sh is missing"
    assert SCRIPT.read_text().startswith("#!/usr/bin/env bash")
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_evaluation_document_is_a_historical_write_up(text):
    """#26 remains evaluation-only in the document; #37 implements it.

    The evaluation write-up must still say it edited no Dockerfile, lock or
    workflow. It must not keep forbidding snapshot.ubuntu.com in the current
    Dockerfile, which is now the #37 implementation.
    """
    assert "Evaluation only" in text
    assert "edits no Dockerfile" in text


def test_the_reproduction_script_rejects_a_future_snapshot_id(tmp_path):
    """A future ID must fail closed before any network call.

    snapshot.ubuntu.com silently serves the moving latest archive for an ID
    that is not in the past, so the script must refuse it.
    """
    result = subprocess.run(
        ["bash", str(SCRIPT), "20990101T000000Z", str(tmp_path), "--download"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2, result.stderr
    assert "not in the past" in result.stderr
    assert not (tmp_path / "img").exists()


def test_the_reproduction_script_treats_download_as_a_flag_not_a_workdir(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPT), "20990101T000000Z", "--download"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=tmp_path,
    )
    assert result.returncode == 2, result.stderr
    assert "not in the past" in result.stderr
    # --download must not be taken as the workdir path.
    assert not (tmp_path / "--download").exists()


def test_q3_states_the_closed_set_holds_only_with_no_install_recommends(text):
    """The 933-closed-set figure holds with --no-install-recommends, the chosen setting.

    Vera reproduced 19 extra Recommends on an empty status and 7 against the
    image when Recommends are left on, as the script and Dockerfile do.
    """
    q3 = _sections(text)[3]
    assert "--no-install-recommends" in q3
    assert re.search(r"chosen setting", q3, flags=re.IGNORECASE)
    assert "left open" not in q3
    assert "19" in q3
    assert re.search(r"\b7\b", q3)
    for package in (
        "less",
        "libcbor0.10",
        "libfido2-1",
        "libxmuu1",
        "openssh-client",
        "patch",
        "xauth",
    ):
        assert package in q3


def test_q4_osrf_group_counts_match_the_lock(text):
    """Q4's per-library pin counts must match tools/ubuntu-packages.lock."""
    pins = []
    for line in (ROOT / "tools/ubuntu-packages.lock").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pins.append(line.split("=", 1)[0])
    groups = {
        "gz-sensors": 41,
        "gz-common": 17,
        "gz-physics": 14,
        "gz-transport": 9,
        "gz-rendering": 7,
    }
    q4 = _sections(text)[4]
    for name, count in groups.items():
        assert sum(name in pin for pin in pins) == count, name
        assert re.search(rf"{re.escape(name)} {count}\b", q4), name


def test_the_reproduction_script_fails_closed_when_apt_update_exits_without_an_err_line(
    tmp_path,
):
    """apt-get update must fail the script even when it prints no Err/E: line."""
    rootfs = tmp_path / "img" / "rootfs"
    (rootfs / "var/lib/dpkg").mkdir(parents=True)
    (rootfs / "var/lib/dpkg/status").write_text(
        "Package: dummy\nStatus: install ok installed\n\n"
    )
    (rootfs / "usr/share/keyrings").mkdir(parents=True)
    (rootfs / "usr/share/keyrings/ubuntu-archive-keyring.gpg").write_bytes(b"")

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "apt-get"
    stub.write_text(
        "#!/bin/bash\necho 'Failed to fetch indexes (no details)'\nexit 1\n"
    )
    stub.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        ["bash", str(SCRIPT), "20261101T000000Z", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert result.returncode == 1, result.stderr + result.stdout
    assert "apt-get update failed" in result.stderr
    # Must stop at update, not continue into lock resolution.
    assert "lock does NOT resolve" not in result.stdout
    assert not (tmp_path / "simulate.out").exists()
