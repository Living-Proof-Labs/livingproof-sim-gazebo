# SPDX-License-Identifier: Apache-2.0
"""Exercise the actual offline and daily lock guards with mutated lock files."""

import re

import pytest

import test_ubuntu_packages_lock as monitor


@pytest.fixture
def recorded_lock(tmp_path, monkeypatch):
    # Construct a known-consistent baseline from the captured index, independent
    # of current lock drift, so each mutation is the only fault under test.
    records = monitor._stanzas(monitor._recorded_osrf_index())
    by_name = {r["Package"]: r for r in records}
    lines = []
    for name, version in monitor._pins(monitor.LOCK):
        if record := by_name.get(monitor._base(name)):
            lines.append(f"{name}={record['Version']} sha256:{record['SHA256']}")
        else:
            lines.append(f"{name}={version}")
    text = "\n".join(lines) + "\n"
    lock = tmp_path / "packages.lock"
    lock.write_text(text)
    monkeypatch.setattr(monitor, "LOCK", lock)
    return lock


def test_recorded_lock_passes_both_guards(recorded_lock):
    monitor.test_locked_osrf_exact_dependencies_match_recorded_index()
    monitor.test_recorded_osrf_only_pins_have_digests()


@pytest.mark.parametrize(
    "mutation", ["single", "uniform", "missing", "no-source-digest"]
)
def test_offline_dependency_guard_rejects_mutations(recorded_lock, mutation):
    text = recorded_lock.read_text()
    if mutation == "uniform":
        text = text.replace("13.7.0-1~noble", "13.6.0-1~noble")
    elif mutation == "missing":
        text = re.sub(r"^libgz-transport13:amd64=.*\n", "", text, flags=re.M)
    else:
        text = text.replace(
            "libgz-transport13:amd64=13.7.0", "libgz-transport13:amd64=13.6.0"
        )
        if mutation == "no-source-digest":
            text = re.sub(r" sha256:[0-9a-f]+", "", text)
    recorded_lock.write_text(text)
    with pytest.raises(AssertionError, match="OSRF exact dependencies:.*transport13"):
        monitor.test_locked_osrf_exact_dependencies_match_recorded_index()


@pytest.mark.parametrize("package", ["gz-tools2:amd64", "libgz-cmake3-dev:amd64"])
@pytest.mark.parametrize("digest", ["", " sha256:invalid"])
def test_offline_digest_guard_rejects_removed_or_malformed_digest(
    recorded_lock, package, digest
):
    text = re.sub(
        rf"^({re.escape(package)}=\S+) sha256:\S+",
        rf"\g<1>{digest}",
        recorded_lock.read_text(),
        flags=re.M,
    )
    recorded_lock.write_text(text)
    with pytest.raises(AssertionError, match=re.escape(package)):
        monitor.test_recorded_osrf_only_pins_have_digests()


@pytest.mark.parametrize("dep_field", ["Depends", "Pre-Depends"])
@pytest.mark.parametrize("version", ["1.0", "2.0", None])
def test_daily_monitor_checks_exact_dependencies(
    tmp_path, monkeypatch, dep_field, version
):
    lock = tmp_path / "packages.lock"
    lock.write_text("gz-example=1.0 sha256:" + "a" * 64 + "\n")
    if version:
        with lock.open("a") as stream:
            stream.write(f"lib-example:amd64={version}\n")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("")
    monkeypatch.setattr(monitor, "LOCK", lock)
    monkeypatch.setattr(monitor, "DOCKERFILE", dockerfile)
    osrf = (
        "Package: gz-example\nVersion: 1.0\nArchitecture: amd64\n"
        f"SHA256: {'a' * 64}\n{dep_field}: unrelated (>= 2),\n lib-example (= 1.0)"
    )
    ubuntu = f"Package: lib-example\nVersion: {version}\nArchitecture: amd64"
    monkeypatch.setattr(
        monitor, "_fetch_packages", lambda url: osrf if url == monitor.OSRF else ubuntu
    )
    check = (
        monitor.test_every_lock_and_dockerfile_pin_is_in_the_live_noble_or_osrf_index
    )
    if version == "1.0":
        check()
    else:
        with pytest.raises(AssertionError, match=r"requires lib-example \(= 1.0\)"):
            check()


@pytest.mark.parametrize("ubuntu_version", ["1.0", "2.0", None])
def test_daily_monitor_requires_digest_only_for_osrf_only_version(
    tmp_path, monkeypatch, ubuntu_version
):
    lock = tmp_path / "packages.lock"
    lock.write_text("gz-example:amd64=1.0\n")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("")
    monkeypatch.setattr(monitor, "LOCK", lock)
    monkeypatch.setattr(monitor, "DOCKERFILE", dockerfile)
    osrf = "Package: gz-example\nVersion: 1.0\nArchitecture: amd64"
    ubuntu = osrf.replace("1.0", ubuntu_version) if ubuntu_version else ""
    monkeypatch.setattr(
        monitor, "_fetch_packages", lambda url: osrf if url == monitor.OSRF else ubuntu
    )
    check = (
        monitor.test_every_lock_and_dockerfile_pin_is_in_the_live_noble_or_osrf_index
    )
    if ubuntu_version == "1.0":
        check()
    else:
        with pytest.raises(
            AssertionError, match="OSRF-only pins without a recorded sha256"
        ):
            check()


@pytest.mark.parametrize("architecture", ["amd64", "all", "arm64"])
def test_exact_dependency_metadata_matches_target_architecture(tmp_path, architecture):
    lock = tmp_path / "packages.lock"
    lock.write_text("gz-example=1.0\n")
    index = f"Package: gz-example\nVersion: 1.0\nArchitecture: {architecture}"
    if architecture == "arm64":
        with pytest.raises(
            AssertionError, match="missing OSRF package/version metadata"
        ):
            monitor._check_exact_dependencies(index, lock)
    else:
        monitor._check_exact_dependencies(index, lock)


def test_exact_alternatives_are_not_silently_ignored(tmp_path):
    lock = tmp_path / "packages.lock"
    lock.write_text("gz-example=1.0\n")
    index = (
        "Package: gz-example\nVersion: 1.0\nArchitecture: amd64\n"
        "Depends: absent (= 1.0) | other (= 2.0)"
    )
    with pytest.raises(AssertionError, match="unsupported exact dependency"):
        monitor._check_exact_dependencies(index, lock)
