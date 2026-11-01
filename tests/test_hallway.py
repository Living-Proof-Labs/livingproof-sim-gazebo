# SPDX-License-Identifier: Apache-2.0
"""Pinned hallway-open fixture: checksums, SDF translation, UNSUPPORTED and hallways.md checks."""

import copy
import json
import shutil
import xml.etree.ElementTree as ET

import pytest

from livingproof_sim_gazebo import contract, hallway

FIXTURE, VERSION = "hallway-open", "0.1.0"


@pytest.fixture(scope="module")
def loaded():
    return hallway.load_fixture(FIXTURE, VERSION)


@pytest.fixture(scope="module")
def result():
    return hallway.run_checks(FIXTURE, VERSION)


@pytest.fixture
def copy_root(tmp_path):
    root = tmp_path / "worlds"
    shutil.copytree(hallway.WORLDS, root)
    return root


def unsupported_record(monkeypatch, loaded, world=None, extension=None):
    fake = {
        **loaded,
        "world": world or loaded["world"],
        "extension": extension or loaded["extension"],
    }
    return hallway.run_checks(FIXTURE, VERSION, loaded=fake)


def test_pin_names_tag_and_full_commit(loaded):
    pin = loaded["pin"]
    assert pin["repository"] == "Living-Proof-Labs/livingproof-worlds"
    assert pin["tag"] == "v1.1.0"
    assert pin["commit"] == "9b3e7119aa93a3370383227fb30bd39a9dd72b4b"
    assert pin["extension"] == "hallway-open-0.1.0.gazebo.json"


def test_tampered_world_file_fails_with_named_mismatch(copy_root):
    path = copy_root / FIXTURE / VERSION / "world.json"
    path.write_text(
        path.read_text().replace('"clear_width": 1.5', '"clear_width": 1.6')
    )
    with pytest.raises(
        hallway.FixtureError, match=r"checksum mismatch for world.json: expected d60bb8"
    ):
        hallway.load_fixture(FIXTURE, VERSION, copy_root)


def test_tampered_release_manifest_fails(copy_root):
    path = copy_root / FIXTURE / VERSION / "release.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(
        hallway.FixtureError, match=r"release.json checksum mismatch.*v1.1.0 9b3e7119"
    ):
        hallway.load_fixture(FIXTURE, VERSION, copy_root)


def test_missing_and_unlisted_files_fail(copy_root):
    directory = copy_root / FIXTURE / VERSION
    (directory / "extra.txt").write_text("x")
    with pytest.raises(
        hallway.FixtureError, match="files not vendored from release.json: extra.txt"
    ):
        hallway.load_fixture(FIXTURE, VERSION, copy_root)
    (directory / "extra.txt").unlink()
    (directory / "notes.md").unlink()
    with pytest.raises(hallway.FixtureError, match="missing released file notes.md"):
        hallway.load_fixture(FIXTURE, VERSION, copy_root)


@pytest.mark.parametrize(
    "fixture,version_", [("hallway-closed", "0.1.0"), ("hallway-open", "0.2.0")]
)
def test_unknown_fixture_or_version_is_reported_not_substituted(fixture, version_):
    with pytest.raises(
        hallway.FixtureError, match=f"unknown fixture {fixture}/{version_}"
    ):
        hallway.load_fixture(fixture, version_)


def test_extension_holds_no_geometry_or_places(loaded):
    assert not {"geometry", "places", "dimensions"} & set(loaded["extension"])


def test_sdf_passes_gz_sdf_check_with_geometry_verbatim_and_places_as_links(
    loaded, tmp_path
):
    sdf = hallway.to_sdf(loaded["world"], loaded["extension"])
    path = tmp_path / "world.sdf"
    path.write_text(sdf)
    check = hallway.sdf_check(path)
    assert check["status"] == "PASS", check
    world = ET.fromstring(sdf).find("world")
    models = {m.get("name"): m for m in world.findall("model")}
    for g in loaded["world"]["geometry"]:
        m = models[g["name"]]
        pose = [float(v) for v in m.find("pose").text.split()]
        size = [
            float(v) for v in m.find("link/collision/geometry/box/size").text.split()
        ]
        assert pose == pytest.approx([*g["centre"], 0, 0, 0])
        assert size == pytest.approx(g["size"])
    links = {link.get("name") for link in models["places"].findall("link")}
    assert {
        "entrance",
        "spawn-exit",
        "passage--min",
        "passage--max",
        "passage-centreline--1",
    } <= links
    assert "probe" not in models and not world.findall(
        ".//sensor"
    )  # no robot or probe in the world


@pytest.mark.parametrize(
    "edit,feature",
    [
        (
            lambda w: w.update(format="livingproof-world/0.2"),
            "world format 'livingproof-world/0.2'",
        ),
        (lambda w: w.update(lights=[]), "top-level field 'lights'"),
        (
            lambda w: w["geometry"][1].update(type="mesh"),
            "geometry 'wall-left' type 'mesh'",
        ),
        (
            lambda w: w["geometry"][2].update(rotation=[0, 0, 5]),
            "geometry 'wall-right' field 'rotation'",
        ),
        (
            lambda w: w["geometry"][0].update(role="ceiling"),
            "geometry 'floor' role 'ceiling'",
        ),
        (
            lambda w: w["places"].append({"name": "door", "type": "door"}),
            "place 'door' type 'door'",
        ),
        (
            lambda w: w["places"][4].update(pitch_deg=5),
            "place 'spawn-entrance' field 'pitch_deg'",
        ),
        (lambda w: w.update(units="ft"), "units 'ft'"),
    ],
)
def test_unmapped_world_feature_is_unsupported(loaded, edit, feature):
    world = copy.deepcopy(loaded["world"])
    edit(world)
    with pytest.raises(hallway.Unsupported) as info:
        hallway.to_sdf(world, loaded["extension"])
    assert str(info.value) == f"UNSUPPORTED: hallway-open 0.1.0: {feature}"


@pytest.mark.parametrize(
    "edit,feature",
    [
        (lambda e: e.update(geometry=[]), "extension field 'geometry'"),
        (lambda e: e.update(places=[]), "extension field 'places'"),
        (
            lambda e: e["surface"].update(surface_layer=0.0),
            "extension field surface.'surface_layer'",
        ),
        (lambda e: e["surface"].update(offset=0.0), "extension field surface.'offset'"),
        (
            lambda e: e["physics"].update(contact_margin=0.0),
            "extension field physics.'contact_margin'",
        ),
        (lambda e: e["probe"].update(pose=[0, 0, 1]), "extension field probe.'pose'"),
        (
            lambda e: e["surface"].update(min_depth=0.001),
            "extension surface.min_depth = 0.001 would move the collision boundary (must be 0)",
        ),
        (
            lambda e: e["surface"].update(soft_cfm=0.01),
            "extension surface.soft_cfm = 0.01 would move the collision boundary (must be 0)",
        ),
        (lambda e: e["physics"].update(engine="bullet"), "physics engine 'bullet'"),
        (
            lambda e: e["probe"].update(radius=0.2),
            "extension probe.radius = 0.2 contradicts hallway-probe.json (0.1)",
        ),
        (
            lambda e: e["probe"].update(mu=0.3),
            "extension probe.mu = 0.3 contradicts hallway-probe.json (0.1)",
        ),
        (
            lambda e: e["probe"].update(max_speed=0.5),
            "extension probe.max_speed = 0.5 contradicts hallway-probe.json (0.25)",
        ),
        (
            lambda e: e["probe"].update(density=500.0),
            "extension probe.density = 500.0 contradicts hallway-probe.json (1000.0)",
        ),
        (
            lambda e: e["physics"].update(gravity=[0.0, 0.0, -9.8]),
            "extension physics.gravity = [0.0, 0.0, -9.8] contradicts hallway-probe.json "
            "([0.0, 0.0, -9.81])",
        ),
        (
            lambda e: e["physics"].update(max_step_size=0.003),
            "extension physics.max_step_size: physics step 0.003 s does not divide the "
            "500 Hz sample period",
        ),
        (
            lambda e: e.update(content_version="0.2.0"),
            "extension written for another fixture or version",
        ),
    ],
)
def test_extension_outside_allowlist_or_moving_boundary_is_unsupported(
    loaded, edit, feature
):
    extension = copy.deepcopy(loaded["extension"])
    edit(extension)
    with pytest.raises(hallway.Unsupported) as info:
        hallway.to_sdf(loaded["world"], extension)
    assert str(info.value) == f"UNSUPPORTED: hallway-open 0.1.0: {feature}"


def test_unsupported_record_keeps_fixture_object_and_validates(loaded):
    extension = copy.deepcopy(loaded["extension"])
    extension["surface"]["min_depth"] = 0.002
    record = hallway.run_checks(
        FIXTURE, VERSION, loaded={**loaded, "extension": extension}
    )
    assert record["status"] == "UNSUPPORTED"
    assert record["fixture"] == {"id": "hallway-open", "content_version": "0.1.0"}
    assert record["feature"].startswith("extension surface.min_depth = 0.002")
    assert record["quantities"] == []
    contract.validate(record)


def test_shared_schema_rejects_a_string_fixture_and_a_short_commit(result):
    bad = {**copy.deepcopy(result), "fixture": "hallway-open"}
    with pytest.raises(contract.ContractError):
        contract.validate(bad)
    bad = copy.deepcopy(result)
    bad["adapter"]["commit"] = "cc3dd22"
    with pytest.raises(contract.ContractError):
        contract.validate(bad)


def test_quantity_names_are_the_shared_names(result):
    names = {q["name"] for q in result["quantities"]}
    assert contract.required_names() <= names
    assert {n for n in names if not n.startswith("reset/")} <= set(contract.names())


def test_result_matches_shared_schema(result):
    contract.validate(result)
    assert result["engine"]["name"] == "gazebo"


def test_all_hallways_md_quantities_pass(result):
    failed = [q["name"] for q in result["quantities"] if not q["pass"]]
    assert result["compile"]["status"] == "PASS"
    assert failed == []
    assert result["status"] == "PASS"
    assert (
        len(result["quantities"]) == 72 + 7
    )  # 71 required, settled_bottom_z, 7 reset/*


def test_probe_comes_from_shared_file(result):
    probe = result["settings"]["probe"]
    assert (probe["radius_m"], probe["friction"]) == (0.1, 0.1)
    assert probe["joints"] == ["slide-x", "slide-y", "slide-z"]
    speeds = [
        q["measured"] for q in result["quantities"] if q["name"].endswith("max_speed")
    ]
    assert speeds and max(speeds) <= 0.25


def test_sampling_keeps_0_001_physics_step_and_samples_every_second_step(result):
    s = result["settings"]
    assert (s["physics_step"], s["sample_rate"], s["sample_stride"]) == (0.001, 500, 2)
    assert s["timestep"] == s["physics_step"]


def test_worker_records_every_second_step_at_500_hz(loaded):
    sdf = hallway.to_sdf(loaded["world"], loaded["extension"], probe=[0.0, 0.0, 0.75])
    run = {"name": "floor", "settle": 0.1, "axis": None}
    out = hallway._worker(sdf, {"run": run, "dt": 0.001, "stride": 2})
    t = [s["t"] for s in out["samples"]]
    assert out["steps"] == 100 and len(t) == 50
    assert all(abs(b - a - 0.002) < 1e-9 for a, b in zip(t, t[1:]))


def test_only_world_notes_release_are_vendored_and_generated_docs_skipped_on_purpose(
    copy_root,
):
    directory = copy_root / FIXTURE / VERSION
    assert sorted(p.name for p in directory.iterdir()) == [
        "notes.md",
        "release.json",
        "world.json",
    ]
    manifest = json.loads((directory / "release.json").read_text())
    skipped = set(manifest["files"]) - hallway.VENDORED
    # release.json lists the generated README and SVG renders; they are deliberately not vendored or checked.
    assert (
        skipped
        == hallway.GENERATED_DOCS
        == {"README.md", "world.svg", "world-light.svg", "world-dark.svg"}
    )
    hallway.load_fixture(FIXTURE, VERSION, copy_root)
    (directory / "world.svg").write_text(
        "<svg/>"
    )  # a generated doc reappearing is still rejected
    with pytest.raises(
        hallway.FixtureError, match="files not vendored from release.json: world.svg"
    ):
        hallway.load_fixture(FIXTURE, VERSION, copy_root)
