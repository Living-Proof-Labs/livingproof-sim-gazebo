# Start here

Living Proof Labs' Gazebo slice runs a falling sphere under native Gazebo Harmonic physics. It records measured positions and can capture a finite headless camera frame. This engine evidence does not establish a robot capability result.

On Ubuntu 24.04 amd64 with Gazebo Harmonic and this package installed:

```sh
livingproof-sim-gazebo --steps 1000 --timeout 180 --output artifacts/trajectory.json --render-output artifacts/frame.png
```

The camera path uses OGRE2, EGL, and software rendering. Physics alone does not require a graphics context. See the [command reference](command.md), [distribution and verification](verification.md), and [MuJoCo manual](https://docs.livingprooflabs.com/livingproof-sim-mujoco/).
