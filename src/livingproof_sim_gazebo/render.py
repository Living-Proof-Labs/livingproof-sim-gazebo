"""Capture one Gazebo camera frame through a finite headless OGRE2 run."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
from xml.sax.saxutils import escape


class RenderInterrupted(Exception):
    def __init__(self, number):
        self.number = number


def capture(output: Path, deadline: float):
    template = (Path(__file__).parent / "models/render.sdf").read_text()
    topic = "/world/falling/model/camera/link/camera_link/sensor/camera/image"
    with tempfile.TemporaryDirectory(prefix="gazebo-render-") as temporary:
        root = Path(temporary)
        frames = root / "frames"
        frames.mkdir()
        world = root / "render.sdf"
        world.write_text(template.replace("__FRAME_DIRECTORY__", escape(str(frames))))
        env = {**os.environ, "LIBGL_ALWAYS_SOFTWARE": "1", "DISPLAY": ""}
        processes = []

        def interrupt(number, _frame):
            raise RenderInterrupted(number)

        previous = {
            number: signal.signal(number, interrupt)
            for number in (signal.SIGINT, signal.SIGTERM)
        }
        with (root / "server.log").open("w+") as log, open(os.devnull, "w") as null:
            try:
                processes.append(
                    subprocess.Popen(
                        [
                            "gz",
                            "sim",
                            "-s",
                            "-r",
                            "--headless-rendering",
                            "--iterations",
                            "1000",
                            str(world),
                        ],
                        stdout=log,
                        stderr=log,
                        env=env,
                        start_new_session=True,
                    )
                )
                processes.append(
                    subprocess.Popen(
                        ["gz", "topic", "-e", "-t", topic],
                        stdout=null,
                        stderr=null,
                        env=env,
                        start_new_session=True,
                    )
                )
                while time.monotonic() < deadline:
                    images = list(frames.glob("*.png"))
                    if images and images[0].stat().st_size > 0:
                        # ImageSaver writes synchronously; wait briefly for the write to finish.
                        time.sleep(0.2)
                        output.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(images[0], output)
                        if output.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                            raise RuntimeError("camera output was not a PNG")
                        return
                    if processes[0].poll() is not None:
                        log.flush()
                        raise RuntimeError(
                            "Gazebo stopped before producing a camera image: "
                            + (root / "server.log").read_text()[-1000:]
                        )
                    time.sleep(0.1)
                raise TimeoutError(
                    "Gazebo camera did not produce a frame before the deadline"
                )
            finally:
                for process in processes:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                for number, handler in previous.items():
                    signal.signal(number, handler)
                for process in processes:
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
