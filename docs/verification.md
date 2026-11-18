# Distribution and verification

The Python wheel and source distribution contain the command, world and Python code; neither bundles the native Gazebo libraries. Ubuntu 24.04 amd64 requires Gazebo Harmonic including Gazebo Sim 8, the Gazebo Python bindings, and OGRE2 and EGL libraries for camera evidence. The development image pins an Ubuntu digest, a dated snapshot.ubuntu.com ID for the Ubuntu archive and security pockets, Gazebo package versions, Task and uv. Ubuntu packages are installed from that snapshot with `--no-install-recommends`. ca-certificates is the one unpinned package: the base image has no CA bundle and the snapshot is https-only, so one live-archive install provides the bundle before sources switch; the locked install then pins the snapshot's ca-certificates. The ISRG root is not vendored. OSRF packages stay on the live OSRF index, with sha256 values recorded next to those pins. This is build-environment pinning, not a robot capability result. An unavailable locked version fails setup rather than silently updating it.

`task setup`, `task check`, `task test`, and `task verify` run directly inside the prepared development container. On a Docker host they route through Compose. The test task publishes individual JUnit cases under `artifacts`. A finite headless capture writes a PNG and trajectory separately from any interactive viewer; no browser preview is included.

The test is a physical engine check, not a robot capability PASS. Native engine support is tested on Ubuntu 24.04 amd64 only. Rendering depends on the OGRE2 and EGL software stack; a successful physics-only run does not prove rendering support.


[Gazebo verification runs](https://github.com/Living-Proof-Labs/livingproof-sim-gazebo/actions/workflows/verify.yml)
provide the actual pass/fail status and 14-day evidence artifacts for each revision.
This manual does not embed or claim fresh native test outcomes. No measured line
coverage report is generated. See [Version and source](version.md) to identify the
documentation revision separately from package releases and test results.

## Development versions

`hatch-vcs` uses setuptools-scm to derive the package version from Git history.
Before the first version tag, an initial no-tag build is `0.0.1.devN`, where `N`
is the commit distance. After tags exist, untagged commits derive their development
version from the nearest version tag; they do not remain `0.0.1.devN`. A clean
version-tag checkout builds that release version. The configured `0.0.0` fallback
is for unavailable version metadata, not the normal untagged Git build.
