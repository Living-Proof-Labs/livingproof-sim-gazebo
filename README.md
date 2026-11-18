# livingproof-sim-gazebo

A bounded, native Gazebo Harmonic physics and camera evidence slice for Living Proof Labs. **[Start here: Gazebo manual](https://docs.livingprooflabs.com/livingproof-sim-gazebo/)**. The companion [MuJoCo manual](https://docs.livingprooflabs.com/livingproof-sim-mujoco/) covers its separate engine implementation.

## Supported platform and native prerequisites

- **Supported platform:** Ubuntu 24.04 (`amd64`) only.
- **Native prerequisites:** Python 3.12 (`>=3.12,<3.13`), **Gazebo Harmonic / Gazebo Sim 8** (`gz-harmonic`, `gz-sim8-cli`, and the Gazebo Python bindings from the OSRF `gazebo-stable` `noble main` apt repository), and **OGRE2 and EGL** software rendering libraries (`libegl1`, `libegl-mesa0`) for camera evidence. Physics-only runs do not require a graphics context. Exact tested apt package pins are in [`tools/ubuntu-packages.lock`](tools/ubuntu-packages.lock) and [`Dockerfile`](Dockerfile).
- **Package scope:** The Python wheel and source distribution contain only the Python CLI, world, and package code (plus `livingproof-common`). **The wheel does not bundle native Gazebo libraries**, and **engine evidence does not establish robot capability or safety certification** (it is not a robot capability PASS). No browser preview, robot stack, or common simulator layer is included.

## Installing a released wheel

Released wheels, source distributions, and `SHA256SUMS` are published on [GitHub Releases](https://github.com/Living-Proof-Labs/livingproof-sim-gazebo/releases). On an Ubuntu 24.04 `amd64` host with the native Gazebo prerequisites installed, verify the checksums and install the wheel into a virtual environment that exposes the system Gazebo Python bindings:

```sh
sha256sum --ignore-missing -c SHA256SUMS
python3 -m venv --system-site-packages .venv
.venv/bin/pip install livingproof_sim_gazebo-<version>-py3-none-any.whl
.venv/bin/livingproof-sim-gazebo --steps 1000 --timeout 180 --output trajectory.json --render-output frame.png
```

## How a release is published

A push to `main` runs verification first. After the entire verification workflow succeeds, a separate release workflow accepts only a same-repository push to `main` whose verified `head_sha` equals the release event’s `github.sha`. The shared release workflow checks out that event revision and asserts `HEAD == GITHUB_SHA` before releasing. If main has moved before the release event, the older verification is rejected; newer main must pass its own verification. A move after the event cannot change the checked-out revision. A draft is created only if that push has releasable commits. It creates a draft release and tag. The `assemble` job checks out that tag, checks that the tag names the **same commit** verification just passed, then re-runs `task verify`, `task package`, and `task smoke` at the tag.

The wheel and sdist cannot be taken from the earlier `verify` job: this package uses `hatch-vcs`, so the version (and the filenames) come from the git tag, which does not exist until the draft is created. Rebuilding at that tag, after proving it names the verified commit, is how the published assets stay tied to the verified run. `SHA256SUMS` is generated from those rebuilt assets, attached to the draft with the wheel and sdist, and only then is the draft published. Tags are not retargeted, and a published release is not altered.

If `assemble` fails after the draft exists, the leftover draft stays **unpublished** and is not a public release. Re-run the failed `assemble` job in that same workflow run: uploads use `--clobber`, so partial assets are replaced and the job can finish without moving the tag. Do not retarget the tag or create a second release. A full re-run of the workflow will not recreate the draft, because the tag already exists; finish the existing draft instead.

## Development and verification

On a Docker host, run `task setup` then `task verify`. Inside the development container the same commands work without Docker. `task test` writes JUnit results and explicit finite trajectory and PNG evidence to `artifacts/`. See [distribution and verification](docs/verification.md).

The [published manual](https://docs.livingprooflabs.com/livingproof-sim-gazebo/) is served through GitHub Pages. See [publication details](docs/contribute.md#publication).
