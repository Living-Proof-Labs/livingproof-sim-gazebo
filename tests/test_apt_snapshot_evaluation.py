# SPDX-License-Identifier: Apache-2.0
"""The #26 apt-snapshot evaluation answers every question and states a verdict.

Evaluation only: the document must answer each of the seven questions in the
issue, name one allowed recommendation, give the dated snapshot it tested (a
past ID, because a future ID resolves to the moving latest archive), say it is not
a robot capability result, and ship the script that reproduces the lock test.
"""

from __future__ import annotations

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


def test_this_evaluation_changes_no_build_input():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "snapshot.ubuntu.com" not in dockerfile
