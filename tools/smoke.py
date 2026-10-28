# SPDX-License-Identifier: Apache-2.0
"""Exercise a built wheel outside the checkout with system Gazebo bindings."""

import json
from pathlib import Path
import subprocess
import tempfile

from PIL import Image

wheels = sorted(Path("dist").glob("livingproof_sim_gazebo-*.whl"))
if len(wheels) != 1:
    raise SystemExit(
        "Expected exactly one Gazebo wheel; clean dist and run task package."
    )
wheel = wheels[0].resolve()
with tempfile.TemporaryDirectory(prefix="gazebo-product-") as temporary:
    root = Path(temporary)
    venv = root / "venv"
    subprocess.run(
        [
            "uv",
            "venv",
            "--system-site-packages",
            "--python",
            "/usr/bin/python3",
            str(venv),
        ],
        check=True,
    )
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv / "bin/python"),
            "--offline",
            str(wheel),
        ],
        check=True,
    )
    command = str(venv / "bin/livingproof-sim-gazebo")
    result = subprocess.run(
        [
            command,
            "--steps",
            "1000",
            "--timeout",
            "180",
            "--output",
            str(root / "trajectory.json"),
            "--render-output",
            str(root / "frame.png"),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=190,
        check=True,
    )
    metadata = json.loads(result.stdout)
    data = json.loads((root / "trajectory.json").read_text())
    if (
        metadata["provenance"] != "recorded-build"
        or abs(data["trajectory"][-1]["z_m"] + 2.909905) > 1e-5
    ):
        raise SystemExit(f"Installed wheel evidence failed: {metadata}")
    with Image.open(root / "frame.png") as image:
        colors = image.convert("RGB").getcolors(320 * 240)
        if (
            image.size != (320, 240)
            or not colors
            or sum(count for count, color in colors if max(color) < 20) <= 20
        ):
            raise SystemExit("Installed wheel camera did not render the sphere")
    print(json.dumps(metadata))
