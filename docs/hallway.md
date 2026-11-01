# Hallway fixture (hallway-open 0.1.0)

The adapter loads the released `hallway-open` 0.1.0 fixture from
[livingproof-worlds](https://github.com/Living-Proof-Labs/livingproof-worlds) **v1.1.0**
(`9b3e7119aa93a3370383227fb30bd39a9dd72b4b`). Only `world.json`, `notes.md` and `release.json` are vendored, unchanged, under
`src/livingproof_sim_gazebo/worlds/hallway-open/0.1.0/`. `worlds/pins.json` records the tag, the full
commit and the SHA-256 of `release.json`. On every load the adapter checks:

- `release.json` against the pinned SHA-256;
- `world.json` and `notes.md` against `release.json`.

`release.json` also lists the generated docs (`README.md`, `world.svg`,
`world-light.svg`, `world-dark.svg`). These are renders of `world.json`, so they are
**skipped on purpose**: they are not vendored and not checksum-checked. A test states
this. Loading fails with a `FixtureError` when:

- a vendored file's checksum does not match;
- a vendored file is missing;
- any other file is present (including a generated doc);
- `release.json` lists a file the adapter doesn't know.

An unknown fixture or version is reported, never substituted.

```console
$ task hallway   # writes artifacts/hallway/{result.json,world.sdf,overhead.png,entrance.png,screenshots.json}
```

## Translation to SDF

- Each `geometry` box becomes a static model with the same name. The model's pose is the
  box `centre` and its collision and visual box `size` is the declared size, copied
  verbatim.
- Places become marker links in a static, collision-free `places` model:
  - `pose` and segment or polyline `reference` points become links named after the place.
  - Each segment and polyline point `i` becomes a link named `<place>--<i>`.
  - A region becomes two corner links, `<place>--min` and `<place>--max`.
- No robot and no probe exist in the world. The probe is only added for the collision
  checks.
- `gz sdf -k` must pass. The test suite and `result.json` (`compile`) run it.

## Gazebo-only settings: `worlds/hallway-open-0.1.0.gazebo.json`

This file holds only allowlisted keys:

| Section | Keys |
|---|---|
| (top level) | `fixture`, `content_version`, `note`, `physics`, `surface`, `probe` |
| `physics` | `engine` (`dartsim` only), `max_step_size`, `gravity` |
| `surface` | `mu`, `mu2`, `kp`, `kd`, `max_vel`, `min_depth`, `soft_cfm` |
| `probe` | `radius`, `density`, `mu`, `drive`, `effort_limit`, `max_speed` |

Any other key, including `geometry`, `places`, a contact margin, a surface layer or an
offset, is **UNSUPPORTED**. `surface.min_depth` and `surface.soft_cfm` let bodies sink
into each other, so they must be `0`; any other value is UNSUPPORTED.

The probe itself is defined by the shared `hallway-probe.json` (see *Result format*).
The extension may only agree with it. These are UNSUPPORTED:

- a different `probe.radius`, `probe.density`, `probe.mu`, `probe.max_speed` or
  `physics.gravity`;
- a `physics.max_step_size` that does not divide the 2 ms sample period.

## UNSUPPORTED

A feature or setting that cannot be mapped faithfully raises
`UNSUPPORTED: <fixture> <version>: <feature>`, for example
`UNSUPPORTED: hallway-open 0.1.0: geometry 'wall-left' type 'mesh'`. The result record
then has `status: "UNSUPPORTED"`, a `feature` string and no quantities. `fixture` stays
the `{id, content_version}` object. The record validates against the vendored shared
schema.

## Checks and probe (shared `hallway-probe.json`)

The adapter runs the `hallways.md` sphere checks. The probe, gravity, start height, settle
and drive times, targets and sample rate all come from the shared probe file, as they do in
livingproof-sim-mujoco:

- **Probe:** a sphere of radius 0.10 m and density 1000 kg/m³, with friction μ = 0.1.
  It is a **sliding probe**: three prismatic joints (x, y, z) and no rotation.
  DART combines friction by taking the minimum, so μ = 0.1 also applies against the
  floor.
- **Drive:** joint velocity commands on the x and y joints, with |command| ≤ **0.25 m/s**.
  A target uses a proportional gain of 10/s. The joint effort limit is 50 N. The probe is
  never teleported.
- **Scenarios:** each scenario starts in a fresh server.
  - Floor drop from rest, settling for 2.0 s.
  - Push into each wall (±y): settle for 1.5 s, then drive for 5 s.
  - Drive to x = ±2.80 m out of each open end (`collision/open_end/+x|-x/…`, target in
    `canonical`). Only floor contact is allowed.
- **Reset** (hallways.md: "Reset restores the geometry, frame, and initial world state"):
  Gazebo Sim 8 with dartsim cannot reset in-process. `Server.reset_all()` returns false,
  and a `WorldControl` `reset.all` request stops the server from stepping. So the reset is a
  **reload**:
  1. One server reads the world back, then drives the probe 1.25 m along +x.
  2. A fresh server loads the same SDF and reads the world back.

  The `reset/*` quantities confirm, each within 0.01 m, that:
  - the box corners are unchanged (`reset/geometry/<name>/max_shift`);
  - the place markers are unchanged (`reset/places/max_shift`);
  - the probe is back at spawn-centre, z = 0.75 (`reset/probe/x|y|z`).
- **Sampling:**
  - The physics step stays at **0.001 s** (dartsim).
  - The ball link world pose and velocity are sampled at the shared **500 Hz**, which is
    every 2nd step. `settings` records `physics_step`, `sample_rate` and `sample_stride`.
  - Contacts are collected from a contact sensor on `/probe/contact`, as the union per
    scenario.
  - Geometry, rotation and place poses are read back from the loaded world: link
    axis-aligned bounding boxes and world poses.

## Result format

`result.json` uses the shared `livingproof-world-result/0.2`. The three contract files
(`hallway-result.schema.json`, `hallway-quantities.json` and `hallway-probe.json`) are
vendored, unchanged, from robot-capability-specs into `src/livingproof_sim_gazebo/contract/`.

`contract/pins.json` is the single place that holds the specs release tag, its commit and each file's
SHA-256. Every load checks them. To re-pin, run
`python tools/pin_contract.py <specs checkout> <tag>`; `--check` confirms the vendored files match the tag. Currently pinned to v1.4.0 (cb57ede).

Each quantity takes its `kind`, `unit` and `comparison` from the shared names. The
comparison decides `pass`:

- `within`: |measured − canonical| ≤ tolerance;
- `at_most`: measured ≤ canonical + tolerance (penetration, distance past a wall face, the
  speed cap).

`adapter.version` is a semantic version. `adapter.commit` is the full commit: from git in a
checkout (`provenance: git`), or from `_build_provenance.json` in an installed package
(`provenance: package`). It is `null` only when neither knows it. `task hallway`
validates the record before writing it.

## Evidence screenshots

`task hallway` renders two views with headless OGRE2 (`--headless-rendering`, software
GL):

- `overhead.png` looks straight down, with +x to the right. It is **near-orthographic,
  not orthographic**. Gazebo Harmonic camera sensors have no orthographic mode: SDF
  `projection_type` applies only to the GUI camera. So the camera sits **60 m** above the
  floor with a **0.12 rad** horizontal field of view. As a result, the tops of the 2.5 m
  walls (57.5 m from the camera) look about **4 % larger** than the floor.
- `entrance.png` is a perspective view from behind the entrance, looking along +x.

If rendering fails, `screenshots.json` marks the view `BLOCKED` with the server log tail.
