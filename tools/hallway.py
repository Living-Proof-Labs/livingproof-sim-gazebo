# SPDX-License-Identifier: Apache-2.0
"""Write the hallway-open evidence bundle: result.json, world.sdf and two camera frames."""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from xml.sax.saxutils import escape

from livingproof_sim_gazebo import hallway

CAMERA = (
    '    <model name="camera-{name}"><static>true</static><pose>{pose}</pose><link name="link">'
    '<sensor name="camera" type="camera"><always_on>true</always_on><update_rate>5</update_rate>'
    "<camera>{projection}<image><width>{w}</width><height>{h}</height><format>R8G8B8</format></image>"
    '<clip><near>0.1</near><far>100</far></clip><save enabled="true"><path>{path}</path></save>'
    "</camera></sensor></link></model>"
)
VIEWS = {
    # Near-orthographic, straight down (+90 deg pitch, +90 deg yaw): +x right, +y up.
    # Gazebo Harmonic camera *sensors* have no orthographic projection (SDF
    # projection_type exists only on the GUI camera), so the camera sits 60 m up
    # with a 0.12 rad field of view: wall tops (2.5 m) render 4% larger than the floor.
    "overhead": {
        "pose": "0 0 60 0 1.5707963 1.5707963",
        "projection": "<horizontal_fov>0.12</horizontal_fov>",
        "w": 1280,
        "h": 480,
    },
    "entrance": {
        "pose": "-4.6 0 1.3 0 0.2 0",
        "projection": "<horizontal_fov>1.2</horizontal_fov>",
        "w": 960,
        "h": 640,
    },
}


def capture(world: dict, extension: dict, out: Path, timeout: float = 240) -> dict:
    """Render every view from one headless server; return {view: path or error}."""
    with tempfile.TemporaryDirectory(prefix="gazebo-hallway-render-") as tmp:
        root = Path(tmp)
        cams = []
        for name, v in VIEWS.items():
            (root / name).mkdir()
            cams.append(CAMERA.format(name=name, path=escape(str(root / name)), **v))
        sdf = root / "render.sdf"
        sdf.write_text(hallway.to_sdf(world, extension, cameras="\n".join(cams)))
        env = {
            **os.environ,
            "LIBGL_ALWAYS_SOFTWARE": "1",
            "DISPLAY": "",
            "GZ_PARTITION": "lpl_" + uuid.uuid4().hex,
        }
        log = (root / "server.log").open("w+")
        procs = [
            subprocess.Popen(
                [
                    "gz",
                    "sim",
                    "-s",
                    "-r",
                    "--headless-rendering",
                    "--iterations",
                    "2000",
                    str(sdf),
                ],
                stdout=log,
                stderr=log,
                env=env,
                start_new_session=True,
            )
        ]
        for name in VIEWS:
            topic = f"/world/{world['id']}/model/camera-{name}/link/link/sensor/camera/image"
            procs.append(
                subprocess.Popen(
                    ["gz", "topic", "-e", "-t", topic],
                    stdout=subprocess.DEVNULL,
                    stderr=log,
                    env=env,
                    start_new_session=True,
                )
            )
        result, deadline = {}, time.monotonic() + timeout
        try:
            while time.monotonic() < deadline and len(result) < len(VIEWS):
                for name in VIEWS:
                    frames = sorted((root / name).glob("*.png"))
                    if (
                        name not in result and len(frames) >= 2
                    ):  # the first frame is complete once a second exists
                        target = out / f"{name}.png"
                        shutil.copyfile(frames[0], target)
                        result[name] = {"status": "PASS", "path": target.name}
                if procs[0].poll() is not None and len(result) < len(VIEWS):
                    break
                time.sleep(0.2)
        finally:
            for p in procs:
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGTERM)
            for p in procs:
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
        log.flush()
        tail = (root / "server.log").read_text()[-800:]
        for name in VIEWS:
            result.setdefault(
                name,
                {"status": "BLOCKED", "error": "no frame from headless ogre2: " + tail},
            )
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/hallway"))
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    loaded = hallway.load_fixture("hallway-open", "0.1.0")
    record = hallway.run_checks("hallway-open", "0.1.0", loaded=loaded)
    from livingproof_sim_gazebo import contract

    contract.validate(record)  # shared 0.2 schema + required names, before writing
    (out / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    (out / "world.sdf").write_text(hallway.to_sdf(loaded["world"], loaded["extension"]))
    shots = capture(loaded["world"], loaded["extension"], out)
    (out / "screenshots.json").write_text(
        json.dumps(
            {
                "views": shots,
                "cameras": VIEWS,
                "robot": None,
                "adapter": record["adapter"],
            },
            indent=2,
        )
        + "\n"
    )
    passed = sum(q["pass"] for q in record["quantities"])
    print(
        f"{record['status']}: {passed}/{len(record['quantities'])} quantities; "
        + ", ".join(f"{k} {v['status']}" for k, v in shots.items())
    )
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
