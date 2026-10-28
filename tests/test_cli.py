"""Exercise the installed command and a real Gazebo falling world."""

import json
import os
import subprocess
import sys


def command(*args):
    return subprocess.run(
        [sys.executable, "-m", "livingproof_sim_gazebo.cli", *args],
        text=True,
        capture_output=True,
        timeout=100,
    )


def test_help():
    result = command("--help")
    assert result.returncode == 0
    assert "--steps" in result.stdout and "--timeout" in result.stdout


def test_invalid_steps():
    result = command("--steps", "0")
    assert result.returncode == 2
    assert "1 to 100000" in result.stderr


def test_timeout():
    result = command("--steps", "100000", "--timeout", "0.001")
    assert result.returncode == 124


def test_version():
    result = command("--version")
    assert result.returncode == 0, result.stderr
    assert "Gazebo Sim, version 8." in json.loads(result.stdout)["engine"]


def test_native_trajectory(tmp_path):
    output = tmp_path / "trajectory.json"
    result = command("--steps", "1000", "--timeout", "60", "--output", str(output))
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text())
    assert data["steps"] == 1000
    assert len(data["trajectory"]) == 1000
    assert abs(data["trajectory"][0]["z_m"] - 1.99999019) < 1e-7
    assert abs(data["trajectory"][-1]["z_m"] - (-2.909905)) < 1e-5
    assert len(data["world_sha256"]) == 64


def test_headless_camera(tmp_path):
    from PIL import Image

    output = tmp_path / "frame.png"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "livingproof_sim_gazebo.cli",
            "--steps",
            "1000",
            "--timeout",
            "180",
            "--render-output",
            str(output),
        ],
        text=True,
        capture_output=True,
        timeout=190,
    )
    assert result.returncode == 0, result.stderr
    with Image.open(output) as image:
        assert image.size == (320, 240)
        pixels = image.convert("RGB").getcolors(320 * 240)
        assert len(pixels) > 2
        assert sum(count for count, color in pixels if max(color) < 20) > 20


def test_sigterm_stops_worker():
    import signal
    import time

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "livingproof_sim_gazebo.cli",
            "--steps",
            "100000",
            "--timeout",
            "120",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(2)
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=10)
    assert process.returncode == 143


def test_missing_engine_is_actionable():
    result = subprocess.run(
        [sys.executable, "-m", "livingproof_sim_gazebo.cli", "--steps", "1"],
        env={**os.environ, "PATH": "/nonexistent"},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "Install Gazebo Sim 8" in result.stderr


def test_invalid_output_path():
    result = command("--steps", "1", "--output", "/dev/null/no-output.json")
    assert result.returncode == 2
    assert "Cannot write evidence" in result.stderr


def test_colliding_output_paths_fail_before_engine_or_writes(tmp_path):
    target = tmp_path / "evidence"
    target.write_bytes(b"original evidence")
    symlink = tmp_path / "symlink"
    symlink.symlink_to(target)
    directory_alias = tmp_path / "directory-alias"
    directory_alias.symlink_to(tmp_path, target_is_directory=True)
    hardlink = tmp_path / "hardlink"
    os.link(target, hardlink)
    cases = [
        (target, target),
        (target, tmp_path / "." / "evidence"),
        (target, symlink),
        (target, hardlink),
        (tmp_path / "new-file", directory_alias / "new-file"),
        (tmp_path / "new-file", tmp_path / "." / "new-file"),
    ]
    for trajectory, image in cases:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "livingproof_sim_gazebo.cli",
                "--output",
                str(trajectory),
                "--render-output",
                str(image),
            ],
            env={**os.environ, "PATH": "/nonexistent"},
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert "must name different files" in result.stderr
        assert target.read_bytes() == b"original evidence"
    assert not (tmp_path / "new-file").exists()
