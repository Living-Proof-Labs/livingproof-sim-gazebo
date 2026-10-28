# Distribution and verification

The Python wheel and source distribution contain the command, world and Python code; neither bundles the native Gazebo libraries. Ubuntu 24.04 amd64 requires Gazebo Harmonic including Gazebo Sim 8, the Gazebo Python bindings, and OGRE2 and EGL libraries for camera evidence. The development image pins an Ubuntu digest, Gazebo package versions, Task and uv. Package availability in upstream apt repositories can change; an unavailable locked version fails setup rather than silently updating it.

`task setup`, `task check`, `task test`, and `task verify` run directly inside the prepared development container. On a Docker host they route through Compose. The test task publishes individual JUnit cases under `artifacts`. A finite headless capture writes a PNG and trajectory separately from any interactive viewer; no browser preview is included.

The test is a physical engine check, not a robot capability PASS. Native engine support is tested on Ubuntu 24.04 amd64 only. Rendering depends on the OGRE2 and EGL software stack; a successful physics-only run does not prove rendering support.
