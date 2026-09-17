"""``tilewright manifest`` against synthetic HDF5: every source tag, parameter reading,
labels, shared axes, identity, collisions, key stamping and where the output lands."""

import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from ruamel.yaml import YAML

from tilewright.contract import ContractError
from tilewright.manifest import generate_manifests, main, manifest_dir

META = {"method": ["INS"], "data_type": "experimental", "material": "NiPS3"}


def write_yaml(path, cfg):
    with open(path, "w") as f:
        YAML().dump(cfg, f)
    return path


def run(tmp_path, cfg, name="ds", **kw):
    yaml_path = write_yaml(tmp_path / f"{name}.yml", cfg)
    ent_path, art_path = generate_manifests(str(yaml_path), **kw)
    return pd.read_parquet(ent_path), pd.read_parquet(art_path)


def files_dataset(tmp_path, n=3, attrs=False):
    d = tmp_path / "runs"
    d.mkdir()
    for i in range(n):
        with h5py.File(d / f"run_{i}.h5", "w") as f:
            if attrs:
                f.attrs["temperature"] = 300.0 + i
                f.attrs["run"] = i
            else:
                f.create_dataset("temperature", data=300.0 + i).attrs["units"] = "K"
                f.create_dataset("run", data=i)
            f.create_dataset("spectrum", data=np.full((4, 2), i, dtype="float32"))
            f.create_dataset("energy", data=np.arange(4.0))
    src = {"directory": str(d), "pattern": "*.h5"}
    if attrs:
        src["params"] = {"group": "/", "from": "attrs"}
    return {"label": "Files Test", "metadata": dict(META), "source": {"files": src},
            "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}],
            "shared": [{"type": "energy", "dataset": "/energy"}]}


# ---------------------------------------------------------------------------

class TestFiles:

    def test_one_entity_per_file(self, tmp_path):
        ent, art = run(tmp_path, files_dataset(tmp_path))
        assert len(ent) == 3 and set(ent.columns) >= {"uid", "temperature", "run", "temperature_units"}
        assert sorted(ent["temperature"]) == [300.0, 301.0, 302.0]
        assert (ent["temperature_units"] == "K").all()
        arts = art[art["uid"].notna()]
        assert len(arts) == 3 and (arts["type"] == "spectrum").all()
        assert json.loads(arts.iloc[0]["shape"]) == [4, 2] and arts.iloc[0]["dtype"] == "float32"
        assert arts.iloc[0]["index"] is None or pd.isna(arts.iloc[0]["index"])

    def test_root_attrs_as_params(self, tmp_path):
        ent, _ = run(tmp_path, files_dataset(tmp_path, attrs=True))
        assert sorted(ent["temperature"]) == [300.0, 301.0, 302.0]

    def test_exclude_applies_to_attrs(self, tmp_path):
        # an attribute is excluded by '<group path>/<name>', and is never read (#5)
        cfg = files_dataset(tmp_path, attrs=True)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f.attrs["note"] = "x"
                entry = f.create_group("entry")
                entry.attrs["title"] = f"scan {i}"
                entry.attrs["version"] = "1.2"
                # an attribute h5py cannot read at all: only excluding it lets manifest pass
                h5py.h5a.create(entry.id, b"stamp", h5py.h5t.UNIX_D32LE,
                                h5py.h5s.create(h5py.h5s.SCALAR))
        cfg["source"]["files"]["params"]["exclude"] = ["/note"]
        ent, _ = run(tmp_path, cfg)
        assert set(ent.columns) == {"uid", "temperature", "run"}
        cfg["source"]["files"]["params"] = {
            "groups": {"root": "/", "entry": "/entry"}, "from": "attrs",
            "exclude": ["/note", "/entry/version", "entry/stamp"]}
        ent, _ = run(tmp_path, cfg, name="ds2")
        assert set(ent.columns) == {"uid", "root.temperature", "root.run", "entry.title"}

    def test_empty_attribute_is_null(self, tmp_path):
        # h5py.Empty, a null dataspace (netCDF's `version = ""`), is stored as null (#5)
        cfg = files_dataset(tmp_path, attrs=True)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f.attrs["version"] = h5py.Empty("S1") if i else "1.2"
        ent, _ = run(tmp_path, cfg)
        version = ent.sort_values("run")["version"]
        assert version.iloc[0] == "1.2" and version.iloc[1:].isna().all()

    def test_empty_dataset_is_null_and_empty_labels_are_left_out(self, tmp_path):
        cfg = files_dataset(tmp_path)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f.create_dataset("spare", data=h5py.Empty("f8"))
                f["temperature"].attrs["comment"] = h5py.Empty("S1")
                f["spectrum"].attrs["long_name"] = h5py.Empty("S1")
        ent, art = run(tmp_path, cfg)
        assert len(ent) == 3 and ent["spare"].isna().all()
        # labels and array metadata carry only str, int and float: an empty one is left out
        assert "temperature_comment" not in ent.columns
        assert (ent["temperature_units"] == "K").all()
        assert "long_name" not in art.columns

    def test_shared_axis_row_has_no_uid(self, tmp_path):
        _, art = run(tmp_path, files_dataset(tmp_path))
        shared = art[art["uid"].isna()]
        assert len(shared) == 1 and shared.iloc[0]["type"] == "energy"
        assert json.loads(shared.iloc[0]["shape"]) == [4]

    def test_key_is_written_into_the_yaml(self, tmp_path):
        cfg = files_dataset(tmp_path)
        yaml_path = write_yaml(tmp_path / "ds.yml", cfg)
        generate_manifests(str(yaml_path))
        text = yaml_path.read_text()
        assert "key: FILES_TEST" in text
        assert list(YAML().load(text).keys())[:2] == ["label", "key"]

    def test_default_output_dir(self, tmp_path):
        ds = tmp_path / ".tilewright" / "datasets"
        ds.mkdir(parents=True)
        cfg = files_dataset(tmp_path)
        yaml_path = write_yaml(ds / "FILES_TEST.yml", cfg)
        ent_path, _ = generate_manifests(str(yaml_path))
        assert Path(ent_path) == tmp_path / ".tilewright" / "manifests" / "FILES_TEST" / "entities.parquet"
        assert manifest_dir(tmp_path / "x" / "ds.yml", "K") == tmp_path / "x" / "manifests" / "K"

    def test_missing_artifact_is_an_error_unless_optional(self, tmp_path):
        cfg = files_dataset(tmp_path)
        cfg["artifacts"].append({"type": "extra", "dataset": "/extra"})
        with pytest.raises(KeyError, match="dataset '/extra' not found"):
            run(tmp_path, cfg)
        cfg["artifacts"][-1]["optional"] = True
        with h5py.File(tmp_path / "runs" / "run_0.h5", "a") as f:
            f.create_dataset("extra", data=np.zeros(3))
        _, art = run(tmp_path, cfg, name="ds2")
        assert (art["type"] == "extra").sum() == 1

    def test_no_files_match(self, tmp_path):
        cfg = files_dataset(tmp_path)
        cfg["source"]["files"]["pattern"] = "*.nxs"
        with pytest.raises(FileNotFoundError, match="no files match"):
            run(tmp_path, cfg)


# ---------------------------------------------------------------------------

def batch_dataset(tmp_path, files=2, n=3):
    d = tmp_path / "sim"
    d.mkdir()
    for b in range(files):
        (d / f"batch_{b}").mkdir()
        with h5py.File(d / f"batch_{b}" / "sim.h5", "w") as f:
            g = f.create_group("params")
            g.create_dataset("alpha", data=np.arange(n, dtype=float) + 10 * b)
            g.create_dataset("beta", data=np.full(n, 0.5))
            g.create_dataset("seed", data=b)  # 0-dim: broadcast
            f.create_dataset("spectra", data=np.zeros((n, 5, 2)))
            f.create_dataset("eloss", data=np.linspace(0, 1, 5))
    return {"label": "Batch Test", "metadata": dict(META),
            "source": {"batch": {"directory": str(d), "pattern": "*/sim.h5",
                                 "params": {"group": "/params"}}},
            "artifacts": [{"type": "spectrum", "dataset": "/spectra"}],
            "shared": [{"type": "eloss", "dataset": "/eloss"}]}


class TestBatch:

    def test_one_entity_per_row(self, tmp_path):
        ent, art = run(tmp_path, batch_dataset(tmp_path))
        assert len(ent) == 6 and sorted(ent["alpha"]) == [0, 1, 2, 10, 11, 12]
        assert set(ent["seed"]) == {0, 1}
        arts = art[art["uid"].notna()]
        assert len(arts) == 6 and json.loads(arts.iloc[0]["shape"]) == [5, 2]
        assert sorted(arts["index"].astype(int)) == [0, 0, 1, 1, 2, 2]

    def test_shared_axis_must_agree_across_files(self, tmp_path):
        cfg = batch_dataset(tmp_path)
        with h5py.File(tmp_path / "sim" / "batch_1" / "sim.h5", "a") as f:
            f["eloss"][...] = np.linspace(0, 2, 5)
        with pytest.raises(ValueError, match="shared axis 'eloss'.*differs"):
            run(tmp_path, cfg)

    def test_shared_axis_missing_everywhere(self, tmp_path):
        cfg = batch_dataset(tmp_path)
        cfg["shared"] = [{"type": "nope", "dataset": "/nope"}]
        with pytest.raises(KeyError, match="shared axis 'nope'"):
            run(tmp_path, cfg)

    def test_artifact_row_mismatch(self, tmp_path):
        cfg = batch_dataset(tmp_path)
        with h5py.File(tmp_path / "sim" / "batch_0" / "sim.h5", "a") as f:
            f.create_dataset("other", data=np.zeros((4, 2)))
        cfg["artifacts"].append({"type": "other", "dataset": "/other", "optional": True})
        with pytest.raises(ValueError, match="leading axis is the entity axis"):
            run(tmp_path, cfg)


# ---------------------------------------------------------------------------

def groups_dataset(tmp_path, n=3):
    d = tmp_path / "grouped"
    d.mkdir()
    with h5py.File(d / "samples.h5", "w") as f:
        f.create_dataset("file_time", data="2026")  # a root dataset is not an entity
        s = f.create_group("samples")
        for i in range(n):
            g = s.create_group(f"sample_{i}")
            g.create_dataset("params/tenDq", data=float(i))
            g.create_dataset("spectrum", data=np.ones((3, 3)) * i)
    return {"label": "Groups Test", "metadata": dict(META),
            "source": {"groups": {"directory": str(d), "entity_group": "/samples",
                                  "params": {"group": "params"}}},
            "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}


class TestGroups:

    def test_one_entity_per_group(self, tmp_path):
        ent, art = run(tmp_path, groups_dataset(tmp_path))
        assert len(ent) == 3 and sorted(ent["tenDq"]) == [0.0, 1.0, 2.0]
        assert sorted(ent["source_group"]) == ["samples/sample_0", "samples/sample_1", "samples/sample_2"]
        assert set(art["dataset"]) == {f"/samples/sample_{i}/spectrum" for i in range(3)}

    def test_top_level_groups_when_no_entity_group(self, tmp_path):
        cfg = groups_dataset(tmp_path)
        del cfg["source"]["groups"]["entity_group"]
        cfg["source"]["groups"]["params"] = None
        cfg["source"]["groups"]["identity"] = "provenance"
        cfg["artifacts"] = [{"type": "spectrum", "dataset": "sample_0/spectrum"}]
        ent, art = run(tmp_path, cfg)
        assert list(ent["source_group"]) == ["samples"]

    def test_missing_artifact_names_the_group(self, tmp_path):
        cfg = groups_dataset(tmp_path)
        cfg["artifacts"] = [{"type": "s", "dataset": "/samples/sample_0/spectrum"}]
        with pytest.raises(KeyError, match="sample_0.*not found"):
            run(tmp_path, cfg)


# ---------------------------------------------------------------------------

class TestTable:

    def test_rows_are_entities(self, tmp_path):
        d = tmp_path / "cncs"
        d.mkdir()
        pd.DataFrame({"run": [1, 2], "Ei": [12.0, 25.0], "filename": ["a.gz", "b.gz"]}
                     ).to_parquet(d / "runs.parquet")
        cfg = {"label": "Table Test", "metadata": dict(META),
               "source": {"table": {"directory": str(d), "path": "runs.parquet", "id": "run",
                                    "locator": {"url": "https://x/{filename}"}}}}
        ent, art = run(tmp_path, cfg)
        assert len(ent) == 2 and list(ent["url"]) == ["https://x/a.gz", "https://x/b.gz"]
        assert len(art) == 0 and list(art.columns)[:4] == ["uid", "type", "file", "dataset"]


# ---------------------------------------------------------------------------

def nexus_file(path, ei, temperature):
    with h5py.File(path, "w") as f:
        entry = f.create_group("entry")
        inst = entry.create_group("instrument")
        inst.create_dataset("Ei", data=ei).attrs["units"] = "meV"
        inst.create_dataset("name", data="SEQUOIA")
        inst.create_dataset("BL17:SEEMeta:JSON", data="{" + "x" * 2000 + "}")
        inst.create_group("detector").create_dataset("distance", data=5.5)
        entry.create_group("sample").create_dataset("chemical_formula", data="NiPS3")
        t = entry.create_group("parameters").create_dataset("temperature", data=temperature)
        t.attrs["units"] = "K"
        data = entry.create_group("data")
        data.create_dataset("data", data=np.zeros((4, 3))).attrs["long_name"] = "Intensity"
        data.create_dataset("E", data=np.arange(4.0) * ei).attrs["units"] = "meV"


@pytest.fixture
def nexus(tmp_path):
    d = tmp_path / "nexus"
    d.mkdir()
    for ei, t in ((30.0, 5.0), (60.0, 6.0)):
        nexus_file(d / f"Ei{int(ei)}.h5", ei, t)
    return {"label": "Nexus Test", "metadata": dict(META),
            "source": {"files": {"directory": str(d), "pattern": "*.h5", "params": {
                "groups": {"instrument": "/entry/instrument", "sample": "/entry/sample",
                           "parameters": "/entry/parameters"},
                "exclude": ["/entry/instrument/BL17:SEEMeta:JSON"]}}},
            "artifacts": [{"type": "data", "dataset": "/entry/data/data"},
                          {"type": "E", "dataset": "/entry/data/E"}]}


class TestParameterGroups:

    def test_groups_become_dotted_columns(self, tmp_path, nexus):
        ent, _ = run(tmp_path, nexus)
        row = ent.sort_values("instrument.Ei").iloc[0]
        assert row["instrument.Ei"] == 30.0 and row["instrument.name"] == "SEQUOIA"
        assert row["sample.chemical_formula"] == "NiPS3" and row["parameters.temperature"] == 5.0
        assert "instrument.BL17:SEEMeta:JSON" not in ent.columns
        assert "instrument.detector.distance" not in ent.columns  # not recursive

    def test_recursive_and_exclude_subgroup(self, tmp_path, nexus):
        nexus["source"]["files"]["params"]["recursive"] = True
        ent, _ = run(tmp_path, nexus)
        assert ent["instrument.detector.distance"].iloc[0] == 5.5
        nexus["source"]["files"]["params"]["exclude"].append("/entry/instrument/detector")
        ent, _ = run(tmp_path, nexus, name="ds2")
        assert "instrument.detector.distance" not in ent.columns

    def test_labels_ride_along_but_do_not_enter_the_uid(self, tmp_path, nexus):
        ent, art = run(tmp_path, nexus)
        assert ent["instrument.Ei_units"].iloc[0] == "meV"
        assert ent["parameters.temperature_units"].iloc[0] == "K"
        uids = set(ent["uid"])
        with h5py.File(tmp_path / "nexus" / "Ei30.h5", "a") as f:
            f["entry/instrument/Ei"].attrs["units"] = "eV"
        ent2, _ = run(tmp_path, nexus, name="ds2")
        assert set(ent2["uid"]) == uids
        by_type = art.set_index("type")
        assert by_type.loc["data", "long_name"].iloc[0] == "Intensity"
        assert by_type.loc["E", "units"].iloc[0] == "meV"

    def test_links_are_resolved_by_the_library(self, tmp_path):
        d = tmp_path / "links"
        d.mkdir()
        with h5py.File(d / "raw.h5", "w") as raw:
            raw.create_dataset("Ei", data=60.0)
            raw.create_dataset("image", data=np.ones((2, 3)))
        with h5py.File(d / "e0.h5", "w") as f:
            f.create_dataset("raw/Ei", data=30.0)
            f.create_dataset("raw/image", data=np.zeros((2, 3)))
            inst = f.create_group("entry/instrument")
            inst["Ei"] = h5py.SoftLink("/raw/Ei")
            inst["Ei_other"] = h5py.ExternalLink("raw.h5", "/Ei")
            inst["gone"] = h5py.SoftLink("/raw/missing")
            f["entry/data/data"] = h5py.SoftLink("/raw/image")
        cfg = {"label": "Links", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "e*.h5",
                                    "params": {"groups": {"instrument": "/entry/instrument"}}}},
               "artifacts": [{"type": "data", "dataset": "/entry/data/data"}]}
        ent, art = run(tmp_path, cfg)
        assert ent.loc[0, "instrument.Ei"] == 30.0 and ent.loc[0, "instrument.Ei_other"] == 60.0
        assert "instrument.gone" not in ent.columns
        assert json.loads(art.loc[0, "shape"]) == [2, 3]


# ---------------------------------------------------------------------------

class TestIdentity:

    def test_params_identity_is_stable_across_file_moves(self, tmp_path):
        ent, _ = run(tmp_path, files_dataset(tmp_path))
        for p in (tmp_path / "runs").glob("*.h5"):
            p.rename(p.with_name("moved_" + p.name))
        ent2, _ = run(tmp_path, _files_cfg_for(tmp_path), name="ds2")
        assert set(ent["uid"]) == set(ent2["uid"])

    def test_provenance_identity_follows_the_path(self, tmp_path):
        cfg = files_dataset(tmp_path)
        cfg["source"]["files"]["identity"] = "provenance"
        ent, _ = run(tmp_path, cfg)
        assert len(set(ent["uid"])) == 3
        (tmp_path / "runs" / "run_0.h5").rename(tmp_path / "runs" / "run_9.h5")
        ent2, _ = run(tmp_path, cfg, name="ds2")
        assert len(set(ent["uid"]) & set(ent2["uid"])) == 2

    def test_identical_params_collide_loudly(self, tmp_path):
        cfg = files_dataset(tmp_path)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f["temperature"][...] = 300.0
                f["run"][...] = 0
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert "3 entities share 1 uids" in msg and "run_0.h5" in msg
        assert "identity: provenance" in msg

    def test_no_params_without_declaring_it_is_an_error(self, tmp_path):
        cfg = files_dataset(tmp_path)
        cfg["source"]["files"]["params"] = {"group": "/nothing_here"}
        with pytest.raises(ValueError, match="no parameters found"):
            run(tmp_path, cfg)

    def test_params_null_uses_provenance(self, tmp_path):
        cfg = files_dataset(tmp_path)
        cfg["source"]["files"]["params"] = None
        ent, _ = run(tmp_path, cfg)
        assert len(ent) == 3 and list(ent.columns) == ["uid"]


def _files_cfg_for(tmp_path):
    d = tmp_path / "runs"
    return {"label": "Files Test", "metadata": dict(META),
            "source": {"files": {"directory": str(d), "pattern": "*.h5"}},
            "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}],
            "shared": [{"type": "energy", "dataset": "/energy"}]}


# ---------------------------------------------------------------------------

class TestCli:

    def test_check_validates_without_writing(self, tmp_path, capsys):
        cfg = files_dataset(tmp_path)
        yaml_path = write_yaml(tmp_path / "ds.yml", cfg)
        assert main([str(yaml_path), "--check"]) == 0
        assert "contract OK: key=FILES_TEST source=files" in capsys.readouterr().out
        assert "key:" not in yaml_path.read_text()
        assert not (tmp_path / "manifests").exists()

    def test_contract_errors_exit_1(self, tmp_path, capsys):
        cfg = files_dataset(tmp_path)
        del cfg["source"]["files"]["directory"]
        yaml_path = write_yaml(tmp_path / "ds.yml", cfg)
        assert main([str(yaml_path)]) == 1
        assert "contract error: source.files.directory is required" in capsys.readouterr().err

    def test_append_skips_existing(self, tmp_path, capsys):
        cfg = files_dataset(tmp_path)
        yaml_path = write_yaml(tmp_path / "ds.yml", cfg)
        assert main([str(yaml_path)]) == 0
        with h5py.File(tmp_path / "runs" / "run_7.h5", "w") as f:
            f.create_dataset("temperature", data=777.0)
            f.create_dataset("run", data=7)
            f.create_dataset("spectrum", data=np.zeros((4, 2), dtype="float32"))
            f.create_dataset("energy", data=np.arange(4.0))
        assert main([str(yaml_path), "--append"]) == 0
        ent = pd.read_parquet(tmp_path / "manifests" / "FILES_TEST" / "entities.parquet")
        assert len(ent) == 4 and "merged: 3 existing + 1 new" in capsys.readouterr().out
