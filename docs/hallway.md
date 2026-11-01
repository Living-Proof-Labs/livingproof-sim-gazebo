# Hallway fixture (hallway-open 0.1.0)

The adapter loads the released `hallway-open` 0.1.0 fixture from
[livingproof-worlds](https://github.com/Living-Proof-Labs/livingproof-worlds) **v1.1.0**
(`9b3e7119aa93a3370383227fb30bd39a9dd72b4b`). The seven released files are copied
unchanged into `src/livingproof_sim_gazebo/worlds/hallway-open/0.1.0/`. Before every
load, the adapter checks `release.json` against the pinned SHA-256 in `worlds/pins.json`
and checks each file against `release.json`. A mismatch, a missing file or an unlisted
file is an error. An unknown fixture or version is reported, never replaced by another.

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
| `probe` | `radius` (0.10 only), `density`, `mu`, `drive`, `effort_limit`, `max_speed` |

Any other key, including `geometry`, `places`, a contact margin, a surface layer or an
offset, is **UNSUPPORTED**. `surface.min_depth` and `surface.soft_cfm` let bodies sink
into each other, so they must be `0`; any other value is UNSUPPORTED.

## UNSUPPORTED

A feature or setting that cannot be mapped faithfully raises
`UNSUPPORTED: <fixture> <version>: <feature>`, for example
`UNSUPPORTED: hallway-open 0.1.0: geometry 'wall-left' type 'mesh'`. The result record
then has `status: "UNSUPPORTED"`, a `feature` string and no quantities. `fixture` stays
the `{id, content_version}` object. The record validates against
`docs/hallway-result.schema.json`.

## Checks and probe choices (same as the MuJoCo adapter)

The adapter runs the `hallways.md` sphere checks with the same probe choices as
livingproof-sim-mujoco, so the two engines produce the same quantity names:

- **Probe:** a sphere of radius 0.10 m and density 1000 kg/m³, with friction μ = 0.1.
  It is a **sliding probe**: three prismatic joints (x, y, z) and no rotation.
  DART combines friction by taking the minimum, so μ = 0.1 also applies against the
  floor.
- **Drive:** joint velocity commands on the x and y joints, with |command| ≤ **0.25 m/s**.
  A target uses a proportional gain of 10/s. The joint effort limit is 50 N. The probe is
  never teleported.
- **Scenarios:** each scenario starts a fresh server, which is the reset.
  - Floor drop from rest.
  - Push into each wall (±y).
  - Drive to x = ±2.80 m out of each open end. Only floor contact is allowed.
- **Sampling:**
  - The ball link world pose and velocity are sampled every physics step (1 ms, dartsim).
  - Contacts are collected from a contact sensor on `/probe/contact`, as the union per
    scenario.
  - Geometry, rotation and place poses are read back from the loaded world: link
    axis-aligned bounding boxes and world poses.

`result.json` uses `livingproof-world-result/0.1`. `adapter.commit` is the full
40-character commit of the checkout (the same pattern as `catalog.commit`), or `null`
when run outside a git checkout.

## Evidence screenshots

`task hallway` renders two views with headless OGRE2 (`--headless-rendering`, software
GL):

- `overhead.png` looks straight down, with +x to the right.
  - Gazebo Harmonic camera sensors have no orthographic projection: SDF `projection_type`
    applies only to the GUI camera.
  - Instead, the camera sits 60 m up with a 0.12 rad field of view. This is
    near-orthographic: the tops of the 2.5 m walls appear about 4 % larger than the floor.
- `entrance.png` is a perspective view from behind the entrance, looking along +x.

If rendering fails, `screenshots.json` marks the view `BLOCKED` with the server log tail.
