# SPDX-License-Identifier: Apache-2.0
"""Exercise the daily monitor offline with controlled package indexes."""

import pytest

import test_ubuntu_packages_lock as monitor


@pytest.mark.parametrize("trailing_blank", [False, True])
@pytest.mark.parametrize("name", ["gz-example", "gz-example:amd64"])
@pytest.mark.parametrize("digest", ["a" * 64, "b" * 64, None])
def test_daily_monitor_compares_hash_for_the_locked_version(
    tmp_path, monkeypatch, name, digest, trailing_blank
):
    lock = tmp_path / "packages.lock"
    lock.write_text(f"{name}=1.0 sha256:{'a' * 64}\n")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("")
    monkeypatch.setattr(monitor, "LOCK", lock)
    monkeypatch.setattr(monitor, "DOCKERFILE", dockerfile)
    # A different version's matching digest must not satisfy the locked version.
    index = (
        "Package: gz-example\nVersion: 2.0\nArchitecture: amd64\nSHA256: "
        + "a" * 64
        + "\n\n"
    )
    index += "Package: gz-example\nVersion: 1.0\nArchitecture: amd64\n"
    if digest is not None:
        index += f"SHA256: {digest}\n"
    if trailing_blank:
        index += "\n"
    monkeypatch.setattr(
        monitor, "_fetch_packages", lambda url: index if url == monitor.OSRF else ""
    )
    check = (
        monitor.test_every_lock_and_dockerfile_pin_is_in_the_live_noble_or_osrf_index
    )
    if digest == "a" * 64:
        check()
    else:
        with pytest.raises(AssertionError, match="OSRF SHA256"):
            check()
