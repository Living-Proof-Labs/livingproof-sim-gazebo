"""Run Gazebo in a separate process, so the caller can enforce a deadline."""

import hashlib
import json
from pathlib import Path
import sys

import gz.math7  # noqa: F401 -- registers Pose3d with pybind
from gz.sim8 import Link, Model, TestFixture, World, world_entity


def main():
    path = Path(sys.argv[1])
    steps = int(sys.argv[2])
    fixture = TestFixture(str(path))
    samples = []

    def post(info, ecm):
        model = Model(World(world_entity(ecm)).model_by_name(ecm, "ball"))
        pose = Link(model.link_by_name(ecm, "body")).world_pose(ecm)
        if pose is not None:
            samples.append({"step": info.iterations, "z_m": pose.pos().z()})

    fixture.on_post_update(post)
    fixture.finalize()
    fixture.server().run(True, steps, False)
    if len(samples) != steps:
        raise RuntimeError(f"expected {steps} samples, got {len(samples)}")
    print(
        json.dumps(
            {
                "world_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "steps": steps,
                "timestep_seconds": 0.001,
                "simulation_time_seconds": steps * 0.001,
                "trajectory": samples,
            }
        )
    )


if __name__ == "__main__":
    main()
