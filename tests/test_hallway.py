# SPDX-License-Identifier: Apache-2.0
"""Pinned hallway-open fixture: checksums, SDF translation, UNSUPPORTED and hallways.md checks."""

import copy
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

import jsonschema
import pytest

from livingproof_sim_gazebo import hallway

FIXTURE, VERSION = "hallway-open", "0.1.0"
SCHEMA = json.loads(Path("docs/hallway-result.schema.json").read_text())
MUJOCO = json.loads(Path("tests/data/mujoco-quantity-names.json").read_text())


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
        hallway.FixtureError, match="files not in release.json: extra.txt"
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
            "probe radius other than the 0.10 m in hallways.md",
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
    jsonschema.validate(record, SCHEMA)


def test_schema_rejects_a_string_fixture_and_a_short_commit(result):
    bad = {**copy.deepcopy(result), "fixture": "hallway-open"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)
    bad = copy.deepcopy(result)
    bad["adapter"]["commit"] = "cc3dd22"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)


def test_adapter_commit_is_full_sha_like_catalog_commit_or_null(
    result, monkeypatch, tmp_path
):
    pattern = re.compile(r"^[0-9a-f]{40}$")
    assert pattern.match(result["catalog"]["commit"])
    commit = result["adapter"]["commit"]
    assert commit is None or pattern.match(commit)
    if (Path(__file__).parents[1] / ".git").exists():
        assert commit is not None
    fake = tmp_path / "pkg" / "src" / "livingproof_sim_gazebo" / "hallway.py"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(hallway, "__file__", str(fake))
    assert hallway.adapter_commit() is None


def test_quantity_names_match_mujoco(result):
    assert sorted(q["name"] for q in result["quantities"]) == sorted(MUJOCO["names"])


def test_result_matches_documented_schema(result):
    jsonschema.validate(result, SCHEMA)
    assert result["engine"]["name"] == "gazebo"


def test_all_hallways_md_quantities_pass(result):
    failed = [q["name"] for q in result["quantities"] if not q["pass"]]
    assert result["compile"]["status"] == "PASS"
    assert failed == []
    assert result["status"] == "PASS"
    assert len(result["quantities"]) == 72


def test_probe_choices_match_mujoco(result):
    probe = result["settings"]["probe"]
    assert (probe["radius"], probe["mu"]) == (0.1, 0.1)
    assert "sliding" in probe["joints"]
    speeds = [
        q["measured"] for q in result["quantities"] if q["name"].endswith("max_speed")
    ]
    assert speeds and max(speeds) <= 0.25 + 1e-6
