"""``tilewright manifest`` against synthetic HDF5: every source tag, parameter reading,
labels, shared axes, identity, collisions, key stamping and where the output lands."""

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from ruamel.yaml import YAML

from tilewright.contract import ContractError, Source
from tilewright.manifest import _check_collisions, _params_uid, generate_manifests, main, manifest_dir

META = {"method": ["INS"], "data_type": "experimental", "material": "NiPS3"}


def sha16(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


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

    def test_params_null_gives_provenance_uids(self, tmp_path):
        cfg = batch_dataset(tmp_path)
        cfg["source"]["batch"]["params"] = None
        ent, art = run(tmp_path, cfg)
        assert list(ent.columns) == ["uid"]
        assert set(ent["uid"]) == {sha16(f"BATCH_TEST:batch_{b}/sim.h5:{i}")
                                   for b in range(2) for i in range(3)}
        assert len(art[art["uid"].notna()]) == 6

    def test_only_1d_members_of_length_n_are_parameters(self, tmp_path):
        cfg = batch_dataset(tmp_path)
        for b in range(2):
            with h5py.File(tmp_path / "sim" / f"batch_{b}" / "sim.h5", "a") as f:
                f["params/column"] = np.zeros((3, 1))
                f["params/bounds"] = np.zeros((3, 2))
                f["params/axis"] = np.zeros(4)
        ent, _ = run(tmp_path, cfg)
        assert set(ent.columns) == {"uid", "alpha", "beta", "seed"}

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

def systems_table(tmp_path, ids="system_id"):
    """Like osti/1846021: system_id repeats, and each repeat differs in one other column."""
    d = tmp_path / "pvdaq"
    d.mkdir(exist_ok=True)
    pd.DataFrame({"system_id": [1332, 1332, 4901, 4901, 7],
                  "tilt": [16.77, 60.0, 20.0, 20.0, 10.0],
                  "azimuth": [180, 180, 270, 90, 180],
                  "site": ["a", "a", "b", "b", "c"]}).to_csv(d / "systems.csv", index=False)
    return {"label": "Systems", "metadata": dict(META),
            "source": {"table": {"directory": str(d), "path": "systems.csv", "id": ids}}}


class TestTable:

    def test_repeated_ids_report_the_columns_that_differ(self, tmp_path):
        with pytest.raises(ValueError) as exc:
            run(tmp_path, systems_table(tmp_path))
        lines = str(exc.value).splitlines()
        assert lines[0] == "SYSTEMS: 4 entities share 2 uids; every entity must be distinct."
        assert lines[1:] == [
            f"  uid {sha16('SYSTEMS:1332')}: system_id=1332 at table rows 0, 1 "
            "(first data row = 0)",
            "    tilt: 16.77 | 60.0",
            f"  uid {sha16('SYSTEMS:4901')}: system_id=4901 at table rows 2, 3 "
            "(first data row = 0)",
            "    azimuth: 270 | 90",
            "Fix: for each uid, list one of the columns that differ in 'id', so that "
            "together they are unique, e.g. id: [system_id, tilt, azimuth].",
        ]

    def test_composite_id_resolves_repeated_ids(self, tmp_path):
        ent, _ = run(tmp_path, systems_table(tmp_path, ids=["system_id", "tilt", "azimuth"]))
        assert len(ent) == 5 and ent["uid"].nunique() == 5
        assert ent.loc[0, "uid"] == sha16('SYSTEMS:[1332, 16.77, 180]')
        assert list(ent["system_id"]) == [1332, 1332, 4901, 4901, 7]

    def test_rows_equal_in_every_column_must_be_deduplicated(self, tmp_path):
        cfg = systems_table(tmp_path, ids=["system_id", "tilt", "azimuth"])
        df = pd.read_csv(tmp_path / "pvdaq" / "systems.csv")
        pd.concat([df, df.iloc[[4]]]).to_csv(tmp_path / "pvdaq" / "systems.csv", index=False)
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        lines = str(exc.value).splitlines()
        assert lines[1:] == [
            f"  uid {sha16('SYSTEMS:[7, 10.0, 180]')}: system_id=7, tilt=10.0, azimuth=180 "
            "at table rows 4, 5 (first data row = 0)",
            "    no column differs",
            "Fix: these rows are equal in every column; de-duplicate the table.",
        ]

    def test_missing_id_column_is_named(self, tmp_path):
        with pytest.raises(KeyError, match="id column 'tilt_deg' not among"):
            run(tmp_path, systems_table(tmp_path, ids=["system_id", "tilt_deg"]))

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
        # one id column: sha256('<KEY>:<value>'), as before ADR-0008
        assert list(ent["uid"]) == [sha16("TABLE_TEST:1"), sha16("TABLE_TEST:2")]
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

    def test_params_collision_report_shows_every_uid_and_what_differs(self, tmp_path):
        cfg = files_dataset(tmp_path, n=4)
        for i in range(4):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f["temperature"][...] = 300.0 + i % 2
                f["run"][...] = i % 2
                f["temperature"].attrs["units"] = "degK" if i > 1 else "K"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        lines = str(exc.value).splitlines()
        assert lines[0] == "FILES_TEST: 4 entities share 2 uids; every entity must be distinct."
        assert lines[1].endswith(": run_0.h5, run_2.h5") and lines[4].endswith(": run_1.h5, run_3.h5")
        assert lines[2] == lines[5] == '    temperature_units: "K" | "degK"'
        assert lines[3] == '    equal: {"run": 0, "temperature": 300.0}'
        assert lines[6] == '    equal: {"run": 1, "temperature": 301.0}'
        assert lines[7].startswith("Fix: add a field that distinguishes them")

    @pytest.mark.parametrize("tag, identity, fix", [
        ("files", "provenance", "the pattern or entity_group is matching the same thing twice"),
        ("groups", "provenance", "the pattern or entity_group is matching the same thing twice"),
        ("batch", "params", "or set 'identity: provenance' under the source"),
    ])
    def test_the_fix_line_follows_the_source(self, tag, identity, fix):
        source = Source.model_validate({tag: {"directory": "/d", "identity": identity}})
        rows = [{"uid": "u", "a": 1, "_provenance": "f.h5"},
                {"uid": "u", "a": 1, "_provenance": "f.h5"}]
        with pytest.raises(ValueError) as exc:
            _check_collisions(rows, "K", source)
        lines = str(exc.value).splitlines()
        assert lines[1:3] == ["  uid u: f.h5, f.h5", "    no parameter differs"]
        assert lines[-1].startswith("Fix: ") and fix in lines[-1]
        assert ("pattern" in lines[-1]) == (identity == "provenance")

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

    @pytest.mark.parametrize("identity", ["params", "provenance"])
    def test_si_scale_parameters_stay_distinct(self, tmp_path, identity):
        # openPMD-style timesteps in seconds: distinct, but all below 5e-13 (#4)
        ent, _ = run(tmp_path, si_dataset(tmp_path, identity))
        assert len(ent) == 3 and ent["uid"].nunique() == 3
        assert sorted(ent["time"]) == SI_TIMES
        assert (ent["dt"] == SI_DT).all()

    def test_floats_are_hashed_at_12_significant_digits(self):
        def uid(**params):
            return _params_uid("K", params)
        # scale-free: SI-scale values stay apart, down to the 12th significant digit
        assert len({uid(time=t) for t in (*SI_TIMES, 0.0)}) == 4
        assert uid(charge=1.602176634e-19) != uid(charge=1.602176635e-19)
        # noise past the 12th significant digit is still not a new entity, at any scale
        assert uid(time=SI_TIMES[0]) == uid(time=SI_TIMES[0] * (1 + 1e-14))
        assert uid(T=300.0) == uid(T=300.0 + 1e-11)
        # values with few digits hash exactly as they did before the change (b268731)
        assert uid(T=300.0, run=1) == "2c4f3c84c370721c"
        assert uid(T=2.5666, label="x") == "75c8ab85fd63385c"


SI_TIMES = [8.390153e-14, 1.007e-13, 1.316102e-13]
SI_DT = 3.290256e-16


def si_dataset(tmp_path, identity):
    """One file per timestep, parameters in seconds (0-dim datasets at the root)."""
    d = tmp_path / "si"
    d.mkdir()
    for i, t in enumerate(SI_TIMES):
        with h5py.File(d / f"step_{i}.h5", "w") as f:
            f.create_dataset("time", data=t).attrs["unitSI"] = 1.0
            f.create_dataset("dt", data=SI_DT)
            f.create_dataset("signal", data=np.full((2, 3), i, dtype="float32"))
    return {"label": "SI Test", "metadata": dict(META),
            "source": {"files": {"directory": str(d), "pattern": "*.h5", "identity": identity}},
            "artifacts": [{"type": "signal", "dataset": "/signal"}]}


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


# ---------------------------------------------------------------------------
# key stamping leaves the author's YAML as written (#14)
# ---------------------------------------------------------------------------

HAND_WRITTEN = """\
# A hand-written header comment.
label: Files Test

metadata:
  method: [INS]            # a flow list
  data_type: experimental
  material: NiPS3
  contact: 'Someone (Somewhere)'
  description: >-
    Three synthetic runs written by the test suite for the key-stamping check, with one
    temperature each; the lines of this folded description are deliberately close to ninety
    columns wide, as hand-written descriptions often are.
  sample_length_mm: 1.50

source:
  files:
    directory: {directory}
    pattern: "*.h5"

artifacts:
  - {{type: spectrum,  dataset: /spectrum}}
shared:
- {{type: energy, dataset: /energy}}
"""

CONTRACT_TAIL = """\
metadata: {method: [INS], data_type: experimental, material: NiPS3}
source: {files: {directory: /d}}
artifacts: [{type: s, dataset: /s}]
"""


def _stamped(tmp_path, text):
    from tilewright.manifest import read_yaml, stamp_key

    path = tmp_path / "ds.yml"
    path.write_bytes(text.encode())
    cfg, raw, _ = read_yaml(path)
    assert stamp_key(path, raw, cfg.catalog_key) is True
    return path.read_bytes().decode()


class TestKeyStamp:

    def test_first_run_adds_only_the_key_line(self, tmp_path):
        files_dataset(tmp_path)
        directory = tmp_path / ("a_directory_name_long_enough_to_push_the_directory_value_"
                                "past_eighty_columns")
        (tmp_path / "runs").rename(directory)
        before = HAND_WRITTEN.format(directory=directory)
        yaml_path = tmp_path / "ds.yml"
        yaml_path.write_text(before)
        generate_manifests(str(yaml_path))
        after = yaml_path.read_text()
        assert after == before.replace("label: Files Test\n",
                                       "label: Files Test\nkey: FILES_TEST\n", 1)
        generate_manifests(str(yaml_path))
        assert yaml_path.read_text() == after

    @pytest.mark.parametrize("eol", ["\r\n", "\r"])
    def test_line_endings_are_kept(self, tmp_path, eol):
        before = ("# header\nlabel: Eol Test\n" + CONTRACT_TAIL).replace("\n", eol)
        assert _stamped(tmp_path, before) == before.replace(
            f"label: Eol Test{eol}", f"label: Eol Test{eol}key: EOL_TEST{eol}")

    def test_label_on_the_last_line_without_a_newline(self, tmp_path):
        before = CONTRACT_TAIL + "label: Last Line  # the label comes last"
        assert _stamped(tmp_path, before) == before + "\nkey: LAST_LINE"

    @pytest.mark.parametrize("label", [
        "label: >-\n  Folded\n  Label\n",
        "label: Folded\n  Label\n",
        "label:\n  Folded Label\n",
        'label: "Folded\n  Label"\n',
    ])
    def test_a_label_on_several_lines_gets_the_key_line_before_it(self, tmp_path, label):
        before = "# header\n" + label + CONTRACT_TAIL
        after = _stamped(tmp_path, before)
        assert after == "# header\nkey: FOLDED_LABEL\n" + label + CONTRACT_TAIL
        assert YAML(typ="safe").load(after)["label"] == "Folded Label"

    def test_an_empty_key_is_filled_in(self, tmp_path):
        after = _stamped(tmp_path, "label: Empty Key\nkey:\n" + CONTRACT_TAIL)
        data = YAML(typ="safe").load(after)
        assert data["key"] == "EMPTY_KEY" and list(data)[:2] == ["label", "key"]

    def test_an_alias_stays_as_written_and_resolves_on_every_load(self, tmp_path):
        from tilewright.manifest import read_yaml

        before = "label: Alias Test\n" + CONTRACT_TAIL.replace("[INS]", "[EDRIXS]")
        after = _stamped(tmp_path, before)
        assert after == before.replace("\n", "\nkey: ALIAS_TEST\n", 1)
        cfg, _, notes = read_yaml(tmp_path / "ds.yml")
        assert cfg.metadata.method == ["RIXS"]
        assert "metadata.method: alias 'EDRIXS' -> 'RIXS'" in notes


# ---------------------------------------------------------------------------
# names reserved for the locators registration writes beside the parameters (#18)
# ---------------------------------------------------------------------------

class TestReservedNames:

    @pytest.mark.parametrize("name", ["path_spectrum", "dataset_spectrum", "index_spectrum"])
    def test_a_files_parameter_named_like_a_locator_is_refused(self, tmp_path, name):
        cfg = files_dataset(tmp_path)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f[name] = f"calib_{i}"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert f"run_0.h5: parameter '{name}' is named like a locator" in msg
        assert "artifact 'spectrum'" in msg
        assert f"Fix: add '/{name}' to params.exclude under the source, or rename it" in msg
        cfg["source"]["files"]["params"] = {"exclude": [f"/{name}"]}
        ent, _ = run(tmp_path, cfg, name="ds2")
        assert name not in ent.columns and len(ent) == 3

    def test_the_cli_names_the_parameter_and_exits_1(self, tmp_path, capsys):
        cfg = files_dataset(tmp_path)
        with h5py.File(tmp_path / "runs" / "run_1.h5", "a") as f:
            f["path_spectrum"] = "calib_A"
        yaml_path = write_yaml(tmp_path / "ds.yml", cfg)
        assert main([str(yaml_path)]) == 1
        err = capsys.readouterr().err
        assert "run_1.h5: parameter 'path_spectrum'" in err and "params.exclude" in err
        assert not (tmp_path / "manifests" / "FILES_TEST" / "entities.parquet").exists()

    def test_a_batch_parameter_in_a_group(self, tmp_path):
        cfg = batch_dataset(tmp_path)
        with h5py.File(tmp_path / "sim" / "batch_0" / "sim.h5", "a") as f:
            f["params/index_spectrum"] = np.arange(3)
        with pytest.raises(ValueError, match=r"parameter 'index_spectrum'(.|\n)*"
                                             r"add '/params/index_spectrum' to params.exclude"):
            run(tmp_path, cfg)

    def test_a_groups_parameter(self, tmp_path):
        cfg = groups_dataset(tmp_path)
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            f["samples/sample_2/params/dataset_spectrum"] = "x"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert "samples.h5:/samples/sample_2: parameter 'dataset_spectrum'" in msg
        assert "add '/params/dataset_spectrum' to params.exclude" in msg

    def test_an_attribute_parameter(self, tmp_path):
        cfg = files_dataset(tmp_path, attrs=True)
        with h5py.File(tmp_path / "runs" / "run_0.h5", "a") as f:
            f.attrs["path_spectrum"] = "calib_A"
        with pytest.raises(ValueError, match=r"parameter 'path_spectrum'(.|\n)*Fix: rename the "
                                             r"attribute 'path_spectrum' in the file; "
                                             r"params.exclude skips datasets"):
            run(tmp_path, cfg)

    def test_a_params_groups_name(self, tmp_path, nexus):
        groups = nexus["source"]["files"]["params"]["groups"]
        groups["path_E"] = groups.pop("sample")
        with pytest.raises(ValueError, match=r"parameter 'path_E.chemical_formula'(.|\n)*"
                                             r"under the name 'path_E'(.|\n)*"
                                             r"Fix: rename 'path_E' under params.groups"):
            run(tmp_path, nexus)

    def test_a_subgroup_read_recursively(self, tmp_path):
        cfg = files_dataset(tmp_path)
        cfg["source"]["files"]["params"] = {"recursive": True}
        with h5py.File(tmp_path / "runs" / "run_0.h5", "a") as f:
            f["path_spectrum/gain"] = 2.0
        with pytest.raises(ValueError, match=r"parameter 'path_spectrum.gain'(.|\n)*"
                                             r"add '/path_spectrum' to params.exclude"):
            run(tmp_path, cfg)

    def test_an_attribute_label(self, tmp_path):
        cfg = files_dataset(tmp_path)
        with h5py.File(tmp_path / "runs" / "run_0.h5", "a") as f:
            f.create_dataset("path", data=1.0).attrs["spectrum"] = "a label"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert ("label 'path_spectrum' (attribute 'spectrum' of parameter 'path') is named "
                "like a locator") in msg
        assert ("add '/path' to params.exclude under the source (this also leaves out the "
                "parameter 'path'), or rename the attribute 'spectrum' in the file") in msg

    def test_other_names_with_a_locator_prefix_are_parameters(self, tmp_path):
        cfg = files_dataset(tmp_path)  # artifact 'spectrum', shared axis 'energy'
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f["path_length"] = 1.5 + i
                f["path_energy"] = "a shared axis has no locator on the entity"
                f["index_spectrum_2"] = i
        ent, _ = run(tmp_path, cfg)
        assert {"path_length", "path_energy", "index_spectrum_2"} <= set(ent.columns)

    def test_a_table_declares_no_artifacts_so_its_columns_never_collide(self, tmp_path):
        d = tmp_path / "picks"
        d.mkdir()
        pd.DataFrame({"trace_name": ["ev1", "ev2"], "path_p_travel_s": [3.5, 4.25],
                      "path_x": ["a.h5", "b.h5"], "dataset_x": ["/x", "/x"],
                      "index_x": [0, 1]}).to_csv(d / "meta.csv", index=False)
        cfg = {"label": "Picks", "metadata": dict(META),
               "source": {"table": {"directory": str(d), "path": "meta.csv",
                                    "id": "trace_name"}}}
        ent, art = run(tmp_path, cfg)
        assert len(ent) == 2 and list(ent["path_p_travel_s"]) == [3.5, 4.25]
        assert len(art) == 0
