# SPDX-License-Identifier: Apache-2.0
"""Load a pinned livingproof-worlds fixture into Gazebo and run the hallway conformance checks.

world.json is the only source of geometry and named places. Gazebo-only settings live in a
small, allowlisted per-world extension file that can never move a collision boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape, quoteattr

WORLDS = Path(__file__).parent / "worlds"
RESULT_FORMAT = "livingproof-world-result/0.1"
SUPPORTED_FORMAT = "livingproof-world/0.1"
GEOMETRY_KEYS = {"name", "type", "role", "centre", "size"}
PLACE_KEYS = {
    "segment": {"name", "type", "points", "reference"},
    "region": {"name", "type", "x", "y"},
    "polyline": {"name", "type", "points"},
    "pose": {"name", "type", "position", "yaw_deg"},
}
WORLD_KEYS = {
    "format",
    "id",
    "content_version",
    "title",
    "description",
    "specification",
    "units",
    "frame",
    "dimensions",
    "geometry",
    "places",
    "tolerances",
    "provenance",
    "license",
}
# Allowlist for hallway-*.gazebo.json. ZERO_ONLY keys would move the collision boundary.
EXTENSION_KEYS = {
    "": {"fixture", "content_version", "note", "physics", "surface", "probe"},
    "physics": {"engine", "max_step_size", "gravity"},
    "surface": {"mu", "mu2", "kp", "kd", "max_vel", "min_depth", "soft_cfm"},
    "probe": {"radius", "density", "mu", "drive", "effort_limit", "max_speed"},
}
ZERO_ONLY = {("surface", "min_depth"), ("surface", "soft_cfm")}
ENGINES = {"dartsim"}


class FixtureError(Exception):
    """The fixture is unknown, not pinned, or does not match its released checksums."""


class Unsupported(Exception):
    """A declared feature or extension setting has no faithful Gazebo mapping."""

    def __init__(self, fixture: str, version_: str, feature: str):
        self.fixture, self.version, self.feature = fixture, version_, feature
        super().__init__(f"UNSUPPORTED: {fixture} {version_}: {feature}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pins() -> dict:
    return json.loads((WORLDS / "pins.json").read_text())


def load_fixture(fixture: str, content_version: str, root: Path = WORLDS) -> dict:
    """Return the pinned world after verifying release.json and every file it lists."""
    key = f"{fixture}/{content_version}"
    pin = pins().get(key)
    if pin is None:
        raise FixtureError(
            f"unknown fixture {key}: pinned fixtures are {', '.join(sorted(pins()))}; "
            "an unknown identifier or version is reported, not substituted"
        )
    directory = root / fixture / content_version
    release = directory / "release.json"
    if not release.is_file():
        raise FixtureError(f"{key}: missing {release}")
    actual = sha256(release)
    if actual != pin["release_sha256"]:
        raise FixtureError(
            f"{key}: release.json checksum mismatch: expected {pin['release_sha256']} "
            f"(livingproof-worlds {pin['tag']} {pin['commit']}), got {actual}"
        )
    manifest = json.loads(release.read_text())
    if (manifest.get("id"), manifest.get("content_version")) != (
        fixture,
        content_version,
    ):
        raise FixtureError(
            f"{key}: release.json names {manifest.get('id')} {manifest.get('content_version')}"
        )
    for name, expected in sorted(manifest["files"].items()):
        path = directory / name
        if not path.is_file():
            raise FixtureError(f"{key}: missing released file {name}")
        got = sha256(path)
        if got != expected:
            raise FixtureError(
                f"{key}: checksum mismatch for {name}: expected {expected}, got {got}"
            )
    extras = sorted(
        p.name for p in directory.iterdir() if p.name not in manifest["files"]
    )
    if extras != ["release.json"]:
        unlisted = ", ".join(e for e in extras if e != "release.json")
        raise FixtureError(f"{key}: files not in release.json: {unlisted}")
    world = json.loads((directory / "world.json").read_text())
    extension = json.loads((root / pin["extension"]).read_text())
    return {"world": world, "extension": extension, "pin": pin}


def supported(world: dict, extension: dict) -> None:
    """Raise Unsupported for the first declared feature or extension key that cannot be mapped."""
    fid, ver = world.get("id", "?"), world.get("content_version", "?")
    if world.get("format") != SUPPORTED_FORMAT:
        raise Unsupported(fid, ver, f"world format {world.get('format')!r}")
    for key in sorted(set(world) - WORLD_KEYS):
        raise Unsupported(fid, ver, f"top-level field {key!r}")
    if world.get("units") != "m":
        raise Unsupported(fid, ver, f"units {world.get('units')!r}")
    for g in world["geometry"]:
        if g.get("type") != "box":
            raise Unsupported(
                fid, ver, f"geometry {g.get('name')!r} type {g.get('type')!r}"
            )
        if g.get("role") not in ("floor", "wall"):
            raise Unsupported(
                fid, ver, f"geometry {g.get('name')!r} role {g.get('role')!r}"
            )
        for key in sorted(set(g) - GEOMETRY_KEYS):
            raise Unsupported(fid, ver, f"geometry {g.get('name')!r} field {key!r}")
    for p in world["places"]:
        allowed = PLACE_KEYS.get(p.get("type"))
        if allowed is None:
            raise Unsupported(
                fid, ver, f"place {p.get('name')!r} type {p.get('type')!r}"
            )
        for key in sorted(set(p) - allowed):
            raise Unsupported(fid, ver, f"place {p.get('name')!r} field {key!r}")
    # Extension: allowlisted keys only; nothing may move a collision boundary.
    for key in sorted(set(extension) - EXTENSION_KEYS[""]):
        raise Unsupported(fid, ver, f"extension field {key!r}")
    if (extension.get("fixture"), extension.get("content_version")) != (fid, ver):
        raise Unsupported(fid, ver, "extension written for another fixture or version")
    for section in ("physics", "surface", "probe"):
        values = extension.get(section)
        if not isinstance(values, dict):
            raise Unsupported(fid, ver, f"extension section {section!r} missing")
        for key in sorted(set(values) - EXTENSION_KEYS[section]):
            raise Unsupported(fid, ver, f"extension field {section}.{key!r}")
        for key in sorted(values):
            if (section, key) in ZERO_ONLY and values[key] != 0:
                raise Unsupported(
                    fid,
                    ver,
                    f"extension {section}.{key} = {values[key]!r} would move the collision "
                    "boundary (must be 0)",
                )
    if extension["physics"].get("engine") not in ENGINES:
        raise Unsupported(
            fid, ver, f"physics engine {extension['physics'].get('engine')!r}"
        )
    if extension["probe"].get("radius") != 0.1:
        raise Unsupported(fid, ver, "probe radius other than the 0.10 m in hallways.md")


def _v(values) -> str:
    return " ".join(repr(float(v)) for v in values)


def _pose(xyz, yaw_deg=0.0) -> str:
    return f"{_v(xyz)} 0 0 {math.radians(yaw_deg)!r}"


def place_points(world: dict) -> list[tuple[str, list[float], float | None]]:
    """(marker name, xyz, yaw or None) for every named place, matching the MuJoCo site names."""
    out = []
    for p in world["places"]:
        n, t = p["name"], p["type"]
        if t == "segment":
            out.append((n, p["reference"], None))
            out += [(f"{n}/{i}", pt, None) for i, pt in enumerate(p["points"])]
        elif t == "polyline":
            out += [(f"{n}/{i}", pt, None) for i, pt in enumerate(p["points"])]
        elif t == "pose":
            out.append((n, p["position"], float(p["yaw_deg"])))
        elif t == "region":
            out.append((f"{n}/min", [p["x"][0], p["y"][0], 0.0], None))
            out.append((f"{n}/max", [p["x"][1], p["y"][1], 0.0], None))
    return out


def link_name(marker: str) -> str:
    return marker.replace("/", "--")


def to_sdf(
    world: dict, extension: dict, probe: list[float] | None = None, cameras: str = ""
) -> str:
    """Translate world.json to SDF 1.9. Geometry is copied verbatim; places become marker links."""
    supported(world, extension)
    ph, su = extension["physics"], extension["surface"]
    surface = (
        f"<surface><friction><ode><mu>{su['mu']}</mu><mu2>{su['mu2']}</mu2></ode></friction>"
        f"<contact><ode><kp>{su['kp']}</kp><kd>{su['kd']}</kd><max_vel>{su['max_vel']}</max_vel>"
        f"<min_depth>{su['min_depth']}</min_depth><soft_cfm>{su['soft_cfm']}</soft_cfm></ode>"
        "</contact></surface>"
    )
    colours = {"floor": "0.80 0.82 0.85 1", "wall": "0.45 0.50 0.58 1"}
    out = [
        '<?xml version="1.0" ?>',
        '<sdf version="1.9">',
        f"  <world name={quoteattr(world['id'])}>",
        f"    <gravity>{_v(ph['gravity'])}</gravity>",
        f'    <physics name="fixed" type="ignored"><max_step_size>{ph["max_step_size"]}</max_step_size>'
        "<real_time_factor>0</real_time_factor></physics>",
        f'    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics">'
        f"<engine><filename>gz-physics-{ph['engine']}-plugin</filename></engine></plugin>",
        '    <plugin filename="gz-sim-contact-system" name="gz::sim::systems::Contact"/>',
        '    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>',
        "    <scene><ambient>0.6 0.6 0.6 1</ambient><background>0.12 0.14 0.18 1</background>"
        "<shadows>false</shadows></scene>",
        '    <light name="sun" type="directional"><pose>0 0 8 0 0 0</pose>'
        "<direction>-0.3 0.2 -1</direction><diffuse>0.9 0.9 0.9 1</diffuse></light>",
    ]
    for g in world["geometry"]:
        box = f"<geometry><box><size>{_v(g['size'])}</size></box></geometry>"
        out.append(
            f"    <model name={quoteattr(g['name'])}><static>true</static>"
            f'<pose>{_pose(g["centre"])}</pose><link name="link">'
            f'<collision name="collision">{box}{surface}</collision>'
            f'<visual name="visual">{box}<material><diffuse>{colours[g["role"]]}</diffuse>'
            f"<ambient>{colours[g['role']]}</ambient></material></visual></link></model>"
        )
    # Places: one static model, one marker link per point (no collisions, so no physics effect).
    out.append('    <model name="places"><static>true</static>')
    for marker, xyz, yaw in place_points(world):
        size = "0.24 0.06 0.01" if yaw is not None else "0.04 0.04 0.01"
        rgba = "0.1 0.3 0.9 1" if yaw is not None else "1 0.5 0 1"
        out.append(
            f"      <link name={quoteattr(link_name(marker))}><pose>{_pose(xyz, yaw or 0.0)}</pose>"
            f'<visual name="v"><geometry><box><size>{size}</size></box></geometry>'
            f"<material><diffuse>{rgba}</diffuse><ambient>{rgba}</ambient></material></visual></link>"
        )
    region = (
        next(p for p in world["places"] if p["type"] == "region")
        if any(p["type"] == "region" for p in world["places"])
        else None
    )
    if region:
        c = [
            (region["x"][0] + region["x"][1]) / 2,
            (region["y"][0] + region["y"][1]) / 2,
            0.0006,
        ]
        s = [region["x"][1] - region["x"][0], region["y"][1] - region["y"][0], 0.001]
        out.append(
            f'      <link name="region-visual--{escape(region["name"])}"><pose>{_pose(c)}</pose>'
            f'<visual name="v"><geometry><box><size>{_v(s)}</size></box></geometry>'
            "<material><diffuse>0.1 0.6 0.5 1</diffuse><ambient>0.1 0.6 0.5 1</ambient></material>"
            "</visual></link>"
        )
    out.append("    </model>")
    if probe is not None:
        pr = extension["probe"]
        r = pr["radius"]
        mass = pr["density"] * 4 / 3 * math.pi * r**3
        inertia = 0.4 * mass * r * r
        small = "<inertial><mass>0.01</mass><inertia><ixx>1e-5</ixx><iyy>1e-5</iyy><izz>1e-5</izz></inertia></inertial>"
        lim = f"<limit><lower>-1e6</lower><upper>1e6</upper><effort>{pr['effort_limit']}</effort><velocity>{pr['max_speed']}</velocity></limit>"
        out += [
            f'    <model name="probe"><pose>{_v(probe)} 0 0 0</pose>',
            f'      <link name="slide-x">{small}</link><link name="slide-y">{small}</link>',
            f'      <link name="ball"><inertial><mass>{mass!r}</mass><inertia><ixx>{inertia!r}</ixx>'
            f"<iyy>{inertia!r}</iyy><izz>{inertia!r}</izz></inertia></inertial>"
            f'<collision name="collision"><geometry><sphere><radius>{r}</radius></sphere></geometry>'
            f"<surface><friction><ode><mu>{pr['mu']}</mu><mu2>{pr['mu']}</mu2></ode></friction>"
            f"<contact><ode><kp>{su['kp']}</kp><kd>{su['kd']}</kd><max_vel>{su['max_vel']}</max_vel>"
            f"<min_depth>0</min_depth></ode></contact></surface></collision>"
            f'<visual name="visual"><geometry><sphere><radius>{r}</radius></sphere></geometry>'
            "<material><diffuse>0.95 0.45 0.1 1</diffuse></material></visual>"
            '<sensor name="contact" type="contact"><always_on>true</always_on><update_rate>0</update_rate>'
            "<contact><collision>collision</collision><topic>/probe/contact</topic></contact></sensor></link>",
            f'      <joint name="probe-x" type="prismatic"><parent>world</parent><child>slide-x</child><axis><xyz>1 0 0</xyz>{lim}</axis></joint>',
            f'      <joint name="probe-y" type="prismatic"><parent>slide-x</parent><child>slide-y</child><axis><xyz>0 1 0</xyz>{lim}</axis></joint>',
            '      <joint name="probe-z" type="prismatic"><parent>slide-y</parent><child>ball</child><axis><xyz>0 0 1</xyz>'
            "<limit><lower>-1e6</lower><upper>1e6</upper></limit></axis></joint>",
            "    </model>",
        ]
    if cameras:
        out.insert(
            4,
            '    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">'
            "<render_engine>ogre2</render_engine></plugin>",
        )
        out.append(cameras)
    out += ["  </world>", "</sdf>"]
    return "\n".join(out) + "\n"


def sdf_check(path: Path) -> dict:
    """Native SDFormat validation with `gz sdf -k`."""
    done = subprocess.run(
        ["gz", "sdf", "-k", str(path)], capture_output=True, text=True, timeout=60
    )
    text = (done.stdout + done.stderr).strip()
    return {
        "status": "PASS" if done.returncode == 0 and "Valid" in text else "FAIL",
        "method": "gz sdf -k",
        "output": text[-500:],
    }


def quantity(name, kind, canonical, measured, tolerance, unit, method):
    deviation = None if measured is None else measured - canonical
    return {
        "name": name,
        "kind": kind,
        "unit": unit,
        "canonical": canonical,
        "measured": measured,
        "deviation": deviation,
        "tolerance": tolerance,
        "pass": deviation is not None and abs(deviation) <= tolerance + 1e-12,
        "method": method,
    }


def _worker(sdf: str, scenario: dict, timeout: float = 300) -> dict:
    with tempfile.TemporaryDirectory(prefix="gazebo-hallway-") as tmp:
        path = Path(tmp) / "world.sdf"
        path.write_text(sdf)
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "livingproof_sim_gazebo._hallway_worker",
                str(path),
                json.dumps(scenario),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    if done.returncode != 0:
        raise RuntimeError(
            f"Gazebo worker failed ({done.returncode}): {done.stderr[-2000:]}"
        )
    return json.loads(done.stdout.strip().splitlines()[-1])


def measure_geometry(read: dict, world: dict) -> list[dict]:
    """Quantities from the loaded Gazebo world: collision AABBs and marker link poses."""
    tol_d, tol_a = world["tolerances"]["distance_m"], world["tolerances"]["angle_deg"]
    d = world["dimensions"]
    boxes = read[
        "boxes"
    ]  # name -> {"min": [..], "max": [..], "yaw_pitch_roll_deg": [..]}
    floor = next(g["name"] for g in world["geometry"] if g["role"] == "floor")
    walls = [g["name"] for g in world["geometry"] if g["role"] == "wall"]
    left = max(walls, key=lambda n: boxes[n]["min"][1])
    right = min(walls, key=lambda n: boxes[n]["min"][1])
    fb, lb, rb = boxes[floor], boxes[left], boxes[right]
    top = fb["max"][2]
    m = "loaded world: Link.world_axis_aligned_box of each collision"
    out = [
        quantity(
            "clear_width",
            "dimension",
            d["clear_width"],
            lb["min"][1] - rb["max"][1],
            tol_d,
            "m",
            m,
        ),
        quantity(
            "length",
            "dimension",
            d["length"],
            fb["max"][0] - fb["min"][0],
            tol_d,
            "m",
            m,
        ),
        *[
            quantity(
                f"length/{n}",
                "dimension",
                d["length"],
                boxes[n]["max"][0] - boxes[n]["min"][0],
                tol_d,
                "m",
                m,
            )
            for n in walls
        ],
        *[
            quantity(
                f"wall_height/{n}",
                "dimension",
                d["wall_height"],
                boxes[n]["max"][2] - top,
                tol_d,
                "m",
                m,
            )
            for n in walls
        ],
        *[
            quantity(
                f"wall_thickness/{n}",
                "dimension",
                d["wall_thickness"],
                boxes[n]["max"][1] - boxes[n]["min"][1],
                tol_d,
                "m",
                m,
            )
            for n in walls
        ],
        quantity(
            "exterior_width",
            "dimension",
            d["exterior_width"],
            lb["max"][1] - rb["min"][1],
            tol_d,
            "m",
            m,
        ),
        quantity(
            "floor_thickness",
            "dimension",
            d["floor_thickness"],
            fb["max"][2] - fb["min"][2],
            tol_d,
            "m",
            m,
        ),
        *[
            quantity(
                f"origin/{a}",
                "frame",
                0.0,
                v,
                tol_d,
                "m",
                "floor top-surface centre from the floor AABB",
            )
            for a, v in zip(
                "xyz",
                (
                    (fb["min"][0] + fb["max"][0]) / 2,
                    (fb["min"][1] + fb["max"][1]) / 2,
                    top,
                ),
            )
        ],
        quantity(
            "inner_face/+y",
            "dimension",
            d["clear_width"] / 2,
            lb["min"][1],
            tol_d,
            "m",
            m,
        ),
        quantity(
            "inner_face/-y",
            "dimension",
            -d["clear_width"] / 2,
            rb["max"][1],
            tol_d,
            "m",
            m,
        ),
    ]
    for n in [floor, *walls]:
        out.append(
            quantity(
                f"axes/{n}",
                "frame",
                0.0,
                read["rotation_deg"][n],
                tol_a,
                "deg",
                "loaded world: rotation angle of the link world pose",
            )
        )
    pm = "loaded world: Link.world_pose of the place marker link"
    poses = read["places"]
    for p in world["places"]:
        n, t = p["name"], p["type"]
        pts = []
        if t == "segment":
            pts = [(n, p["reference"])] + [
                (f"{n}/{i}", pt) for i, pt in enumerate(p["points"])
            ]
        elif t == "polyline":
            pts = [(f"{n}/{i}", pt) for i, pt in enumerate(p["points"])]
        elif t == "pose":
            pts = [(n, p["position"])]
        for marker, pt in pts:
            pos = poses[marker]["xyz"]
            out += [
                quantity(f"place/{marker}/{a}", "place", float(c), v, tol_d, "m", pm)
                for a, c, v in zip("xyz", pt, pos)
            ]
        if t == "region":
            lo, hi = poses[f"{n}/min"]["xyz"], poses[f"{n}/max"]["xyz"]
            for a, i in (("x", 0), ("y", 1)):
                out.append(
                    quantity(
                        f"place/{n}/{a}_min",
                        "place",
                        float(p[a][0]),
                        lo[i],
                        tol_d,
                        "m",
                        pm + "s (min/max corners)",
                    )
                )
                out.append(
                    quantity(
                        f"place/{n}/{a}_max",
                        "place",
                        float(p[a][1]),
                        hi[i],
                        tol_d,
                        "m",
                        pm + "s (min/max corners)",
                    )
                )
        if t == "pose":
            canonical = float(p["yaw_deg"])
            yaw = poses[n]["yaw_deg"]
            yaw = canonical + ((yaw - canonical + 180) % 360 - 180)
            out.append(
                quantity(
                    f"place/{n}/yaw",
                    "place",
                    canonical,
                    yaw,
                    tol_a,
                    "deg",
                    pm + " (yaw about +z)",
                )
            )
    return out


def collision_checks(world: dict, extension: dict) -> tuple[list[dict], dict]:
    tol = world["tolerances"]["distance_m"]
    pr = extension["probe"]
    r, speed = pr["radius"], pr["max_speed"]
    half = world["dimensions"]["clear_width"] / 2
    sdf = to_sdf(world, extension, probe=[0.0, 0.0, 0.75])
    out = []
    dt = extension["physics"]["max_step_size"]
    plan = [
        {"name": "floor", "settle": 2.0, "axis": None},
        {"name": "+y", "settle": 1.5, "axis": "y", "speed": speed, "seconds": 5.0},
        {"name": "-y", "settle": 1.5, "axis": "y", "speed": -speed, "seconds": 5.0},
        {
            "name": "+2.80",
            "settle": 1.5,
            "axis": "x",
            "target": 2.8,
            "speed": speed,
            "seconds": 16.0,
        },
        {
            "name": "-2.80",
            "settle": 1.5,
            "axis": "x",
            "target": -2.8,
            "speed": speed,
            "seconds": 16.0,
        },
    ]
    # A fresh server per scenario is the reset: geometry, frame and initial state are reloaded.
    runs = {r["name"]: _worker(sdf, {"run": r, "dt": dt}) for r in plan}
    drop = runs["floor"]["samples"]
    out.append(
        quantity(
            "collision/floor/penetration",
            "collision",
            0.0,
            max(0.0, max(-(s["z"] - r) for s in drop)),
            tol,
            "m",
            "max over all steps of (floor top - sphere bottom), floored at 0",
        )
    )
    out.append(
        quantity(
            "collision/floor/settled_bottom_z",
            "collision",
            0.0,
            drop[-1]["z"] - r,
            tol,
            "m",
            "sphere bottom z after 2.0 s",
        )
    )
    for sign, label in ((1, "+y"), (-1, "-y")):
        push = runs[label]["samples"]
        touched = sorted(set(runs[label]["contacts"]) - {"floor"})
        max_speed = max(abs(s["vy"]) for s in push)
        out.append(
            quantity(
                f"collision/wall{label}/surface_past_inner_face",
                "collision",
                0.0,
                max(0.0, max(sign * s["y"] + r - half for s in push)),
                tol,
                "m",
                "max over steps of (sphere surface - inner face), floored at 0",
            )
        )
        out.append(
            {
                **quantity(
                    f"collision/wall{label}/max_speed",
                    "drive",
                    speed,
                    max_speed,
                    0.0,
                    "m/s",
                    "max |vy| over steps; must not exceed the drive limit",
                ),
                "deviation": max_speed - speed,
                "pass": max_speed <= speed + 1e-9,
            }
        )
        out.append(
            {
                **quantity(
                    f"collision/wall{label}/reached_wall",
                    "collision",
                    1.0,
                    1.0 if touched else 0.0,
                    0.0,
                    "bool",
                    "probe contacted a wall collision",
                ),
                "contacts": touched,
            }
        )
    for target in (2.8, -2.8):
        run = runs[f"{target:+.2f}"]["samples"]
        touched = sorted(runs[f"{target:+.2f}"]["contacts"])
        others = [c for c in touched if c != "floor"]
        out.append(
            quantity(
                f"collision/open_end/{target:+.2f}/final_x",
                "collision",
                target,
                run[-1]["x"],
                tol,
                "m",
                "probe centre x after drive along passage-centreline",
            )
        )
        out.append(
            {
                **quantity(
                    f"collision/open_end/{target:+.2f}/non_floor_contacts",
                    "collision",
                    0.0,
                    float(len(others)),
                    0.0,
                    "count",
                    "distinct non-floor collisions contacted",
                ),
                "contacts": touched,
            }
        )
        out.append(
            quantity(
                f"collision/open_end/{target:+.2f}/max_abs_y",
                "collision",
                0.0,
                max(abs(s["y"]) for s in run),
                tol,
                "m",
                "max |y| during the drive",
            )
        )
    step = extension["physics"]["max_step_size"]
    notes = {
        "floor_contacts": runs["floor"]["contacts"],
        "gravity": [float(v) for v in extension["physics"]["gravity"]],
        "contacts_enabled": True,
        "physics_engine": extension["physics"]["engine"],
        "timestep": step,
        "sampling_hz": round(1.0 / step, 6),
        "drive_method": f"{pr['drive']}, |command| <= {speed} m/s (proportional 10/s toward a target), "
        f"joint effort limit {pr['effort_limit']} N; no teleporting",
        "measurement_method": "ball link world pose and velocity sampled every physics step; contacts are the union of contact-sensor messages per scenario",
        "probe": {
            "radius": r,
            "density": pr["density"],
            "mu": pr["mu"],
            "joints": "x, y, z prismatic (sliding, no rotation)",
        },
    }
    return out, notes


def adapter_commit() -> str | None:
    """Full 40-character commit of this checkout, or None outside a git checkout."""
    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists() or not (root / "pyproject.toml").is_file():
        return None
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError:
        return None
    sha = done.stdout.strip()
    return sha if done.returncode == 0 and len(sha) == 40 else None


def adapter_identity() -> dict:
    from livingproof_sim_gazebo.cli import identity

    ident = identity()
    return {"name": "livingproof-sim-gazebo", **ident, "commit": adapter_commit()}


def base_record(world: dict, pin: dict, fixture: str, content_version: str) -> dict:
    from livingproof_sim_gazebo.cli import identity

    spec = world["specification"]
    engine = identity()["engine"]
    return {
        "format": RESULT_FORMAT,
        "fixture": {"id": fixture, "content_version": content_version},
        "contract": {
            "world_contract_revision": spec["world_contract_revision"],
            "document": spec["path"],
            "document_revision": spec["document_revision"],
        },
        "catalog": {
            "repository": spec["repository"],
            "tag": spec["tag"],
            "commit": spec["commit"],
        },
        "worlds": {
            k: pin[k] for k in ("repository", "tag", "commit", "path", "release_sha256")
        },
        "engine": {"name": "gazebo", "version": engine.split("version ")[-1]},
        "adapter": adapter_identity(),
    }


def run_checks(
    fixture: str, content_version: str, root: Path = WORLDS, loaded: dict | None = None
) -> dict:
    """Return one engine-neutral result record (docs/hallway-result.schema.json)."""
    loaded = loaded or load_fixture(fixture, content_version, root)
    world, extension, pin = loaded["world"], loaded["extension"], loaded["pin"]
    base = base_record(world, pin, fixture, content_version)
    try:
        sdf = to_sdf(world, extension)
    except Unsupported as exc:
        # The fixture stays an object; the feature is recorded beside it.
        return {
            **base,
            "status": "UNSUPPORTED",
            "feature": exc.feature,
            "quantities": [],
        }
    with tempfile.TemporaryDirectory(prefix="gazebo-hallway-") as tmp:
        path = Path(tmp) / "world.sdf"
        path.write_text(sdf)
        check = sdf_check(path)
    read = _worker(sdf, {"markers": [m for m, _, _ in place_points(world)], "dt": 0.0})
    quantities = measure_geometry(read, world)
    collisions, notes = collision_checks(world, extension)
    quantities += collisions
    ok = check["status"] == "PASS" and all(q["pass"] for q in quantities)
    return {
        **base,
        "status": "PASS" if ok else "FAIL",
        "compile": check,
        "settings": {"extension": pin["extension"], **notes},
        "quantities": quantities,
    }
