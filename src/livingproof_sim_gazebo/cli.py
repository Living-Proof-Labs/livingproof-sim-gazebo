"""Bounded, headless native Gazebo physics."""

import argparse
import hashlib
import json
import math
import os
import signal
import time
from pathlib import Path
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

from livingproof_common.versioning import Consumer, current_version


def identity(timeout=10):
    display, package, source = current_version(
        Consumer("livingproof-sim-gazebo", Path(__file__).parent)
    )
    try:
        common = version("livingproof-common")
    except PackageNotFoundError:
        common = "unavailable"
    engine = subprocess.run(
        ["gz", "sim", "--version"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    ).stdout.splitlines()[0]
    if not engine.startswith("Gazebo Sim, version 8."):
        raise ValueError(f"expected Gazebo Sim 8, got {engine}")
    return {
        "version": display,
        "package_version": package,
        "provenance": source,
        "livingproof_common": common,
        "engine": engine,
    }


def positive_int(value):
    try:
        n = int(value)
        if 0 < n <= 100000:
            return n
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(
        "expected an integer from 1 to 100000, for example 1000"
    )


def positive_time(value):
    try:
        n = float(value)
        if math.isfinite(n) and n > 0:
            return n
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("expected finite positive seconds, for example 60")


def parser():
    parser = argparse.ArgumentParser(
        prog="livingproof-sim-gazebo",
        description="Run the built-in falling-sphere world in Gazebo Harmonic without a display.",
        epilog="Example: livingproof-sim-gazebo --steps 1000 --output artifacts/trajectory.json. Engine execution does not prove robot capability.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="show package, provenance, and native engine versions",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without a viewer (the default and only mode)",
    )
    parser.add_argument("--steps", type=positive_int, default=1000)
    parser.add_argument(
        "--timeout", type=positive_time, default=60.0, help="wall deadline in seconds"
    )
    parser.add_argument(
        "--output", type=Path, help="write trajectory JSON to this path"
    )
    parser.add_argument(
        "--render-output",
        type=Path,
        help="capture a finite headless OGRE2 PNG at this path",
    )
    return parser


def main():
    args = parser().parse_args()
    started = time.monotonic()
    try:
        metadata = identity(min(10, args.timeout))
    except subprocess.TimeoutExpired:
        print(
            "Deadline expired while checking Gazebo; try --timeout 120.",
            file=sys.stderr,
        )
        return 124
    except (OSError, subprocess.SubprocessError, IndexError, ValueError) as exc:
        print(
            f"Gazebo Harmonic is unavailable: {exc}. Install Gazebo Sim 8 and retry.",
            file=sys.stderr,
        )
        return 2
    if args.version:
        print(json.dumps(metadata))
        return 0
    world = Path(__file__).parent / "models/falling.sdf"
    remaining = args.timeout - (time.monotonic() - started)
    if remaining <= 0:
        print(
            "Deadline expired before Gazebo started; try --timeout 120.",
            file=sys.stderr,
        )
        return 124
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "livingproof_sim_gazebo._worker",
            str(world),
            str(args.steps),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    class Stopped(Exception):
        def __init__(self, number):
            self.number = number

    def stop(number, _frame):
        raise Stopped(number)

    old = {
        number: signal.signal(number, stop)
        for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        stdout, stderr = process.communicate(timeout=remaining)
    except (subprocess.TimeoutExpired, Stopped) as exc:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        if isinstance(exc, Stopped):
            return 128 + exc.number
        print(f"Gazebo exceeded {args.timeout:g}s. Try --timeout 120.", file=sys.stderr)
        return 124
    finally:
        for number, handler in old.items():
            signal.signal(number, handler)
    if process.returncode:
        print(
            f"Gazebo worker failed (exit {process.returncode}): {stderr.strip()}\nInstall Gazebo Harmonic and its Python bindings, then retry.",
            file=sys.stderr,
        )
        return 2
    try:
        evidence = json.loads(stdout)
    except json.JSONDecodeError:
        print("Gazebo returned invalid evidence.", file=sys.stderr)
        return 2
    evidence.update(metadata)
    if args.render_output:
        from .render import RenderInterrupted, capture

        try:
            capture(args.render_output, started + args.timeout)
        except RenderInterrupted as exc:
            return 128 + exc.number
        except TimeoutError as exc:
            print(f"Headless camera capture timed out: {exc}", file=sys.stderr)
            return 124
        except (OSError, RuntimeError) as exc:
            print(f"Headless camera capture failed: {exc}", file=sys.stderr)
            return 2
        evidence["render_output"] = str(args.render_output)
        evidence["render_sha256"] = hashlib.sha256(
            args.render_output.read_bytes()
        ).hexdigest()
        evidence["render_world_sha256"] = hashlib.sha256(
            (Path(__file__).parent / "models/render.sdf").read_bytes()
        ).hexdigest()
        evidence["renderer"] = "OGRE2 with EGL; LIBGL_ALWAYS_SOFTWARE=1"
        evidence["render_run"] = "separate finite camera simulation"

    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, indent=2) + "\n")
        except OSError as exc:
            print(f"Cannot write evidence to {args.output}: {exc}", file=sys.stderr)
            return 2
    print(json.dumps({k: v for k, v in evidence.items() if k != "trajectory"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
