# livingproof-sim-gazebo

A bounded, native Gazebo Harmonic physics and camera evidence slice for Living Proof Labs. **[Start with the manual](https://docs.livingprooflabs.com/livingproof-sim-gazebo/)**. The companion [MuJoCo manual](https://docs.livingprooflabs.com/livingproof-sim-mujoco/) covers its separate engine implementation.

On a Docker host, run `task setup` then `task verify`. Inside the development container the same commands work without Docker. `task test` writes JUnit results and explicit finite trajectory and PNG evidence to `artifacts/`. The wheel contains the command and world but not native Gazebo; see [distribution and verification](docs/verification.md).

The tested target is Ubuntu 24.04 amd64, Gazebo Harmonic / Gazebo Sim 8. The software camera path uses OGRE2 and EGL. Engine evidence is not a robot capability PASS. No browser preview, robot stack, or common simulator layer is included.

The manual link names the intended publication location; deployment has not yet been verified.
