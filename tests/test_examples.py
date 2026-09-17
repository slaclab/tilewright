"""The annotated example YAMLs are part of the contract surface: each must validate with
no vocabulary warning, since they are what producers copy, and each must use the source
tag its filename promises."""

import re
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from ruamel.yaml import YAML

from tilewright.contract import load_dataset
from tilewright.manifest import generate_manifests

EXAMPLES = sorted((Path(__file__).parent.parent / "examples" / "datasets").glob("*.yml"))


def test_one_example_per_source_tag():
    assert {"files", "batch", "groups", "table"} <= {p.stem.split("_")[0] for p in EXAMPLES}


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_validates_with_no_warnings(path):
    with open(path) as f:
        raw = YAML().load(f)
    cfg, warnings = load_dataset(raw)
    assert warnings == [], f"{path.name}: {warnings}"
    assert path.stem.startswith(cfg.source.tag)
    assert raw.get("key") == cfg.catalog_key, "examples carry the key manifest would write"


def test_commented_group_entries_in_the_files_example_do_what_they_say(tmp_path):
    """Each '# - {type: ...}' line under artifacts in files.yml is an entry an author
    uncomments. On the layout its comments draw, the two give the artifacts they name, and
    the optional one is skipped for a file without its group."""
    path = next(p for p in EXAMPLES if p.stem == "files")
    lines = re.findall(r"^  # (- \{type: .*?\})(?:\s+#.*)?$", path.read_text(), flags=re.M)
    assert len(lines) == 2
    raw = YAML(typ="safe").load(path.read_text())
    raw["artifacts"] += [YAML(typ="safe").load(line)[0] for line in lines]
    data = tmp_path / "runs"
    data.mkdir()
    for run, channels in ((1, True), (2, False)):
        with h5py.File(data / f"run_{run:04d}.h5", "w") as f:
            f["tenDq"], f["sigma"] = 1.0 * run, 0.1
            f["spectrum"], f["energy"] = np.zeros((151, 40)), np.arange(151.0)
            for k in range(100):
                f[f"frames/frame_{k:04d}"] = np.zeros((64, 64), dtype="uint8")
            f["frames/dark"] = np.zeros((64, 64), dtype="uint8")  # not a frame_*
            for c in "abcd" if channels else "":
                f[f"channels/ch_{c}"] = np.zeros(600)
    raw["source"]["files"]["directory"] = str(data)
    assert load_dataset(raw)[1] == []
    yaml_path = tmp_path / "files.yml"
    with open(yaml_path, "w") as f:
        YAML().dump(raw, f)
    _, art_path = generate_manifests(str(yaml_path), tmp_path / "m")
    art = pd.read_parquet(art_path)
    frames = [f"frame_{k:04d}" for k in range(100)]
    traces = [f"trace_ch_{c}" for c in "abcd"]
    assert list(art.loc[art["file"] == "run_0001.h5", "type"]) == ["spectrum", *frames,
                                                                   *traces, "energy"]
    assert list(art.loc[art["file"] == "run_0002.h5", "type"]) == ["spectrum", *frames]


def test_commented_params_in_the_files_example_validate():
    """Each '# params: ...' line in files.yml is an alternative an author uncomments."""
    path = next(p for p in EXAMPLES if p.stem == "files")
    lines = re.findall(r"^\s*# (params: .*?)(?:\s+#.*)?$", path.read_text(), flags=re.M)
    assert any("location:" in line for line in lines)
    for line in lines:
        raw = YAML(typ="safe").load(path.read_text())
        raw["source"]["files"].update(YAML(typ="safe").load(line))
        cfg, warnings = load_dataset(raw)
        assert warnings == [], line
        if cfg.source.body.params is not None and cfg.source.body.params.location:
            match = re.search(cfg.source.body.params.location, "run_0001.h5")
            assert match and match.groupdict() == {"run": "0001"}


def test_commented_alternatives_in_the_groups_example_do_what_they_say(tmp_path):
    """Each run of '#   <key>: ...' lines in the source block of groups.yml replaces
    entity_group and params. Built on the layouts its comments draw, each gives the
    entities and values the comments promise."""
    path = next(p for p in EXAMPLES if p.stem == "groups")
    blocks = re.findall(r"((?:^    #   (?:entity_group|exclude_groups|params): .*\n)+)",
                        path.read_text(), flags=re.M)
    nested, beside = [YAML(typ="safe").load(re.sub(r"(?m)^    #   ", "", b)) for b in blocks]
    assert "exclude_groups" in nested and nested["params"]["groups"]
    assert beside["params"] == {"group": ".."}

    data = tmp_path / "data"
    data.mkdir()
    with h5py.File(data / "sites.h5", "w") as f:
        for site, gain in (("east", 1.5), ("west", 2.0)):
            f[f"{site}/calibration/gain"] = gain
            for detector in ("det_a", "det_b", "det_c"):
                f[f"{site}/{detector}/spectrum"] = np.zeros(3)
    with h5py.File(data / "scans.h5", "w") as f:
        f["run/beam_current"] = np.arange(12.0)
        for i in range(1, 13):
            f[f"run/scan_{i:02d}/spectrum"] = np.zeros(3)

    found = {}
    for name, alternative in (("sites", nested), ("scans", beside)):
        raw = YAML(typ="safe").load(path.read_text())
        raw["source"]["groups"].update(alternative, directory=str(data), pattern=f"{name}.h5")
        assert load_dataset(raw)[1] == []
        yaml_path = tmp_path / f"{name}.yml"
        with open(yaml_path, "w") as f:
            YAML().dump(raw, f)
        ent_path, art_path = generate_manifests(str(yaml_path), tmp_path / name)
        found[name] = pd.read_parquet(ent_path)
        assert len(pd.read_parquet(art_path)) == len(found[name])

    sites = found["sites"]
    assert len(sites) == 6 and sites["uid"].nunique() == 6
    assert list(zip(sites["site"], sites["detector"], sites["calibration.gain"]))[2:4] == [
        ("east", "det_c", 1.5), ("west", "det_a", 2.0)]
    scans = found["scans"]
    assert list(scans["source_group"]) == [f"run/scan_{i:02d}" for i in range(1, 13)]
    assert list(scans["beam_current"]) == list(np.arange(12.0))
