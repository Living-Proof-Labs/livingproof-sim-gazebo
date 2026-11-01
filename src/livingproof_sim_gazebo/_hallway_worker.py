# SPDX-License-Identifier: Apache-2.0
"""Run one hallway scenario in a fresh Gazebo server and print JSON (internal)."""

import json
import math
from pathlib import Path
import sys
import threading

import gz.math7  # noqa: F401 -- registers Pose3d/Vector3d with pybind
from gz.msgs10.contacts_pb2 import Contacts
from gz.sim8 import Joint, Link, Model, TestFixture, World, world_entity
from gz.transport13 import Node


def vec(v):
    return [v.x(), v.y(), v.z()]


def rotation_deg(pose):
    q = pose.rot()
    return math.degrees(2 * math.acos(min(1.0, abs(q.w()))))


def yaw_deg(pose):
    q = pose.rot()
    return math.degrees(
        math.atan2(
            2 * (q.w() * q.z() + q.x() * q.y()), 1 - 2 * (q.y() ** 2 + q.z() ** 2)
        )
    )


def main():
    path, scenario = Path(sys.argv[1]), json.loads(sys.argv[2])
    names = [m for m in ("floor", "wall-left", "wall-right")]
    fixture = TestFixture(str(path))
    state = {"enabled": False, "samples": [], "read": None, "step": 0}
    contacts, lock = set(), threading.Lock()
    node = Node()

    def on_contacts(msg):
        with lock:
            for c in msg.contact:
                for col in (c.collision1.name, c.collision2.name):
                    model = col.split("::")[0]
                    if model != "probe":
                        contacts.add(model)

    run = scenario.get("run")
    if run and not node.subscribe(Contacts, "/probe/contact", on_contacts):
        raise RuntimeError("could not subscribe to /probe/contact")

    def pre(info, ecm):
        world = World(world_entity(ecm))
        if not state["enabled"]:
            for n in names:
                Link(
                    Model(world.model_by_name(ecm, n)).link_by_name(ecm, "link")
                ).enable_bounding_box_checks(ecm, True)
            if run:
                Link(
                    Model(world.model_by_name(ecm, "probe")).link_by_name(ecm, "ball")
                ).enable_velocity_checks(ecm, True)
            state["enabled"] = True
        if not run:
            return
        probe = Model(world.model_by_name(ecm, "probe"))
        t = info.iterations * scenario["dt"]
        vx = vy = 0.0
        if t > run["settle"] and run["axis"]:
            if run.get("target") is None:
                v = run["speed"]
            else:
                x = state["samples"][-1]["x"] if state["samples"] else 0.0
                v = max(
                    -abs(run["speed"]),
                    min(abs(run["speed"]), 10.0 * (run["target"] - x)),
                )
            vx, vy = (v, 0.0) if run["axis"] == "x" else (0.0, v)
        Joint(probe.joint_by_name(ecm, "probe-x")).set_velocity(ecm, [vx])
        Joint(probe.joint_by_name(ecm, "probe-y")).set_velocity(ecm, [vy])

    def post(info, ecm):
        world = World(world_entity(ecm))
        if not run:
            if info.iterations < 3:
                return
            boxes, rot = {}, {}
            for n in names:
                link = Link(
                    Model(world.model_by_name(ecm, n)).link_by_name(ecm, "link")
                )
                box = link.world_axis_aligned_box(ecm)
                if box is None:
                    return
                boxes[n] = {"min": vec(box.min()), "max": vec(box.max())}
                rot[n] = rotation_deg(link.world_pose(ecm))
            places = {}
            model = Model(world.model_by_name(ecm, "places"))
            for marker in scenario["markers"]:
                pose = Link(
                    model.link_by_name(ecm, marker.replace("/", "--"))
                ).world_pose(ecm)
                places[marker] = {"xyz": vec(pose.pos()), "yaw_deg": yaw_deg(pose)}
            state["read"] = {"boxes": boxes, "rotation_deg": rot, "places": places}
            return
        ball = Link(Model(world.model_by_name(ecm, "probe")).link_by_name(ecm, "ball"))
        pose, vel = ball.world_pose(ecm), ball.world_linear_velocity(ecm)
        if pose is None or vel is None:
            return
        p, v = vec(pose.pos()), vec(vel)
        if not all(math.isfinite(a) for a in p + v):
            raise RuntimeError("non-finite probe state")
        state["samples"].append(
            {
                "t": info.iterations * scenario["dt"],
                "x": p[0],
                "y": p[1],
                "z": p[2],
                "vx": v[0],
                "vy": v[1],
            }
        )

    fixture.on_pre_update(pre)
    fixture.on_post_update(post)
    fixture.finalize()
    steps = (
        5
        if not run
        else int(round((run["settle"] + run.get("seconds", 0.0)) / scenario["dt"]))
    )
    fixture.server().run(True, steps, False)
    if not run:
        if state["read"] is None:
            raise RuntimeError("loaded world returned no bounding boxes")
        print(json.dumps(state["read"]))
        return
    import time

    time.sleep(0.5)  # let the last contact messages arrive
    with lock:
        found = sorted(contacts)
    print(json.dumps({"samples": state["samples"], "contacts": found, "steps": steps}))


if __name__ == "__main__":
    main()
