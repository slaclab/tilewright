"""``tilewright manifest`` against synthetic HDF5: every source tag, parameter reading,
labels, shared axes, identity, collisions, key stamping and where the output lands."""

import contextlib
import hashlib
import json
import math
import re
import signal
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from ruamel.yaml import YAML

from tilewright.contract import ContractError, ParamsSpec, Source
from tilewright.manifest import (_check_collisions, _outside, _params_uid, generate_manifests,
                                 main, manifest_dir)

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


@contextlib.contextmanager
def stops_within(seconds):
    """Fail, instead of hanging the test run, when the block does not finish in time."""
    def stop(signum, frame):
        raise TimeoutError(f"not finished after {seconds} s")
    previous = signal.signal(signal.SIGALRM, stop)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


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

    def test_a_link_cycle_at_an_artifact_dataset_is_named_not_a_traceback(self, tmp_path,
                                                                         capsys):
        """#40: an artifact's own path can be a link chain HDF5 refuses to follow, which is
        a RuntimeError and not the KeyError a dangling link raises, so it escaped and
        killed the command with a traceback naming no file and no artifact. An optional
        artifact is now named and skipped; a required one ends the run with the file, the
        type, the path and HDF5's own message."""
        cfg = files_dataset(tmp_path)
        cfg["artifacts"].append({"type": "dark", "dataset": "/dark", "optional": True})
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f["dark"] = h5py.SoftLink("/dark_2")
                f["dark_2"] = h5py.SoftLink("/dark")
        capsys.readouterr()
        with stops_within(30):
            ent, art = run(tmp_path, cfg)
        assert len(ent) == 3 and set(art["type"]) == {"spectrum", "energy"}
        out = capsys.readouterr().out
        assert out.count("dataset '/dark' unreadable") == 3, out

        cfg["artifacts"][-1]["optional"] = False       # required: the run ends, with a name
        with pytest.raises(KeyError, match=r"run_0\.h5: artifact type='dark' dataset "
                                           r"'/dark' unreadable"):
            run(tmp_path, cfg, name="ds2")

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

    @pytest.mark.parametrize("identity", ["params", "provenance"])
    def test_size_one_member_is_broadcast_whatever_the_batch_length(self, tmp_path, identity):
        # a NeXus-style scalar, shape (1,), in batches of 3 rows and in a batch of 1 row (#4)
        cfg = batch_dataset(tmp_path)
        cfg["source"]["batch"]["identity"] = identity
        for b in range(2):
            with h5py.File(tmp_path / "sim" / f"batch_{b}" / "sim.h5", "a") as f:
                f["params"].create_dataset("gain", data=[1.5 + b])
        (tmp_path / "sim" / "batch_2").mkdir()
        with h5py.File(tmp_path / "sim" / "batch_2" / "sim.h5", "w") as f:
            g = f.create_group("params")
            g.create_dataset("alpha", data=[99.0])  # length N == 1: one value per row, too
            g.create_dataset("beta", data=[0.5])
            g.create_dataset("seed", data=2)
            g.create_dataset("gain", data=[3.5])
            f.create_dataset("spectra", data=np.zeros((1, 5, 2)))
            f.create_dataset("eloss", data=np.linspace(0, 1, 5))
        ent, art = run(tmp_path, cfg)
        assert len(ent) == 7 and ent["uid"].nunique() == 7
        assert dict(zip(ent["alpha"], ent["gain"])) == {
            0: 1.5, 1: 1.5, 2: 1.5, 10: 2.5, 11: 2.5, 12: 2.5, 99: 3.5}
        assert set(ent["beta"]) == {0.5} and sorted(set(ent["seed"])) == [0, 1, 2]
        assert sorted(art.loc[art["file"] == "batch_2/sim.h5", "index"].dropna()) == [0]

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

    def test_a_slash_in_params_is_the_entity_group_not_the_file_root(self, tmp_path):
        """The params.group description says so: under 'groups', '/' is the entity group
        and '/params' is 'params'; the root's 'file_time' is never read."""
        cfg = groups_dataset(tmp_path)
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            for i in range(3):
                f[f"samples/sample_{i}"].create_dataset("gain", data=10 + i)
        for n, group in enumerate(["/", "/params", "params"]):
            cfg["source"]["groups"]["params"] = {"group": group}
            ent, _ = run(tmp_path, cfg, name=f"ds{n}")
            assert list(ent.columns) == ["uid", "source_group",
                                         "gain" if group == "/" else "tenDq"]

    def test_shared_axis_copies_in_every_entity_group_must_agree(self, tmp_path):
        """#37: the entity groups of one file each hold their own copy, and a shared entry
        can name only one of them. Comparing files alone compares none of the copies, so a
        wrong claim of sharedness registered silently and every other entity was served an
        axis that was not its own."""
        cfg = groups_dataset(tmp_path)
        cfg["shared"] = [{"type": "axis", "dataset": "/samples/sample_0/axis"}]
        samples = tmp_path / "grouped" / "samples.h5"
        with h5py.File(samples, "a") as f:
            for i in range(3):
                f[f"samples/sample_{i}"]["axis"] = np.array([0.0, 1.0, 2.0])

        ent, art = run(tmp_path, cfg)
        shared = art[art["uid"].isna()]
        assert len(ent) == 3 and len(shared) == 1
        assert shared.iloc[0]["dataset"] == "/samples/sample_0/axis"

        with h5py.File(samples, "a") as f:            # a sibling copy that is not the same
            f["samples/sample_1/axis"][...] = np.array([9.0, 9.0, 9.0])
        with pytest.raises(ValueError, match=r"shared axis 'axis'.*differs between "
                                             r"samples\.h5:/samples/sample_0/axis and "
                                             r"samples\.h5:/samples/sample_1/axis"):
            run(tmp_path, cfg, name="ds2")

    def test_a_shared_axis_beside_the_entity_groups_is_one_copy_per_file(self, tmp_path):
        """A path outside the entity groups is not multiplied by them: one copy per file,
        as under the other tags."""
        cfg = groups_dataset(tmp_path)
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            f["axis"] = np.array([0.0, 1.0, 2.0])
        cfg["shared"] = [{"type": "axis", "dataset": "/axis"}]
        _, art = run(tmp_path, cfg)
        assert list(art[art["uid"].isna()]["dataset"]) == ["/axis"]

    def test_every_file_is_compared_in_its_own_entity_groups(self, tmp_path):
        """#37: the entity groups a copy is looked for in are those of the file being read,
        not those of the file that holds the path the entry names. A second file whose
        groups carry other names holds nothing at that path, so comparing it there compares
        nothing at all and its entities are served an axis that is not theirs."""
        d = tmp_path / "unlike"
        d.mkdir()

        def write(name, groups):
            with h5py.File(d / name, "w") as f:
                for group, axis in groups.items():
                    g = f.create_group(f"samples/{group}")
                    g.create_dataset("spectrum", data=np.ones((3, 3)))
                    g.create_dataset("axis", data=np.array(axis))

        write("a.h5", {"sample_0": [0.0, 1.0, 2.0], "sample_1": [0.0, 1.0, 2.0]})
        write("b.h5", {"sample_2": [0.0, 1.0, 2.0]})       # a name a.h5 does not hold
        cfg = {"label": "Unlike Groups", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "entity_group": "/samples",
                                     "identity": "provenance"}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}],
               "shared": [{"type": "axis", "dataset": "/samples/sample_0/axis"}]}
        ent, art = run(tmp_path, cfg)
        assert len(ent) == 3
        assert list(art[art["uid"].isna()]["dataset"]) == ["/samples/sample_0/axis"]

        write("b.h5", {"sample_2": [9.0, 9.0, 9.0]})       # the other file's only copy
        with pytest.raises(ValueError, match=r"shared axis 'axis'.*differs between "
                                             r"a\.h5:/samples/sample_0/axis and "
                                             r"b\.h5:/samples/sample_2/axis"):
            run(tmp_path, cfg, name="ds2")

    def test_a_link_cycle_among_the_entity_groups_is_named_and_skipped(self, tmp_path, capsys):
        """#40: two names in the entity groups' parent that link to each other make a chain
        HDF5 refuses to follow. Deciding whether each name is a group resolved it, so the
        RuntimeError escaped and killed the command with a traceback naming no file and no
        group. Each is now named and skipped, and the real entity groups are read."""
        cfg = groups_dataset(tmp_path)
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            f["samples/loop_a"] = h5py.SoftLink("/samples/loop_b")
            f["samples/loop_b"] = h5py.SoftLink("/samples/loop_a")
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        assert len(ent) == 3 and sorted(ent["tenDq"]) == [0.0, 1.0, 2.0]
        out = capsys.readouterr().out
        for name in ("loop_a", "loop_b"):
            assert f"samples.h5:/samples/{name} unreadable" in out, out

    def test_a_link_cycle_at_a_shared_axis_copy_is_named_and_passed_over(self, tmp_path,
                                                                        capsys):
        """#40: a copy of a shared axis that HDF5 will not resolve is a place that does not
        hold the path, and is named rather than ending the run."""
        cfg = groups_dataset(tmp_path)
        cfg["shared"] = [{"type": "axis", "dataset": "/samples/sample_0/axis"}]
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            for i in (0, 2):
                f[f"samples/sample_{i}/axis"] = np.array([0.0, 1.0, 2.0])
            f["samples/sample_1/axis"] = h5py.SoftLink("/samples/sample_1/axis_2")
            f["samples/sample_1/axis_2"] = h5py.SoftLink("/samples/sample_1/axis")
        capsys.readouterr()
        with stops_within(30):
            ent, art = run(tmp_path, cfg)
        assert len(ent) == 3
        assert list(art[art["uid"].isna()]["dataset"]) == ["/samples/sample_0/axis"]
        assert "samples.h5:/samples/sample_1/axis unreadable" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# nested entity groups (ADR-0011, #11)

SITE_LOCATION = r":/(?P<site>[^/]+)/(?P<detector>[^/]+)$"


def sites_dataset(tmp_path):
    """Like osti/1972213: the entity is two group levels deep (/<site>/<detector>), and a
    sibling group, /<site>/calibration, holds values for every detector of its site. The
    two sites have different calibration sets, and every detector reads the same
    temperature, so only the location tells two detectors of one site apart."""
    d = tmp_path / "sites"
    d.mkdir()
    with h5py.File(d / "detectors.h5", "w") as f:
        f.create_dataset("created", data="2026-09-17")  # a root dataset matches no glob
        for site, detectors, calibration in (
                ("south", ["det_c", "det_a"], {"gain": 2.0}),
                ("north", ["det_b", "det_a"], {"gain": 1.5, "offset": 0.25, "channels": 8})):
            for name, value in calibration.items():
                f.create_dataset(f"{site}/calibration/{name}", data=value)
            f[f"{site}/calibration/gain"].attrs["units"] = "counts/keV"
            f.create_dataset(f"{site}/calibration/notes", data="bench 4")
            for det in detectors:
                f.create_dataset(f"{site}/{det}/temperature", data=77.0)
                f.create_dataset(f"{site}/{det}/spectrum", data=np.zeros(4))
        f.create_group("empty_site").create_dataset("status", data=0)  # matches, no entity
    return {"label": "Detectors", "metadata": dict(META),
            "source": {"groups": {"directory": str(d), "entity_group": "/*",
                                  "exclude_groups": ["calibration"],
                                  "params": {"groups": {"calibration": "../calibration",
                                                        "readout": "/"},
                                             "exclude": ["../calibration/notes"],
                                             "location": SITE_LOCATION}}},
            "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}


def scans_dataset(tmp_path, names=None, exclude=("calibration",)):
    """Like zenodo/3528199: per-scan values stored beside the scan groups, as 1-D arrays
    with one element per scan, in the sorted order of the scan names."""
    names = names or [f"scan_{i:02d}" for i in range(1, 13)]
    d = tmp_path / "scans"
    d.mkdir()
    with h5py.File(d / "run.h5", "w") as f:
        run_ = f.create_group("run")
        run_.create_dataset("beam_current", data=np.arange(len(names)) * 10.0)
        run_["beam_current"].attrs["units"] = "mA"
        run_.create_dataset("energy", data=8.0)              # 0-dim: every scan
        run_.create_dataset("mode", data=np.array([3]))      # size 1: every scan
        run_.create_dataset("shutter", data=np.ones(5))      # another length: skipped
        run_.create_dataset("frame", data=np.ones((len(names), 2)))  # 2-D: skipped
        run_.create_group("calibration").create_dataset("dark", data=np.zeros(2))
        for name in names:
            run_.create_dataset(f"{name}/image", data=np.zeros((2, 2)))
    return {"label": "Scans", "metadata": dict(META),
            "source": {"groups": {"directory": str(d), "entity_group": "/run",
                                  "exclude_groups": list(exclude),
                                  "params": {"group": ".."}}},
            "artifacts": [{"type": "image", "dataset": "image"}]}


class TestNestedGroups:

    def test_a_glob_entity_group_takes_the_subgroups_of_every_match(self, tmp_path):
        ent, art = run(tmp_path, sites_dataset(tmp_path))
        assert list(ent["source_group"]) == ["north/det_a", "north/det_b",
                                             "south/det_a", "south/det_c"]
        assert list(art["dataset"]) == [f"/{g}/spectrum" for g in ent["source_group"]]
        assert list(ent.columns) == [
            "uid", "source_group", "site", "detector", "calibration.channels",
            "calibration.gain", "calibration.offset", "readout.temperature",
            "calibration.gain_units"]
        assert list(ent["site"]) == ["north", "north", "south", "south"]
        assert list(ent["calibration.gain"]) == [1.5, 1.5, 2.0, 2.0]
        assert list(ent["calibration.gain_units"]) == ["counts/keV"] * 4
        assert ent.loc[0, "uid"] == params_uid("DETECTORS", {
            "site": "north", "detector": "det_a", "calibration.channels": 8,
            "calibration.gain": 1.5, "calibration.offset": 0.25,
            "readout.temperature": 77.0})

    def test_entities_lacking_a_parameter_get_null(self, tmp_path):
        """docs/explanation/data-model.md: a column one entity lacks is null for it, and
        a column of integers with a null in it is written as floats."""
        ent, _ = run(tmp_path, sites_dataset(tmp_path))
        assert ent["calibration.offset"].isna().tolist() == [False, False, True, True]
        assert ent["calibration.channels"].tolist()[:2] == [8.0, 8.0]
        assert pd.api.types.is_float_dtype(ent["calibration.channels"])
        # the uid is computed before the table is built: the value stays the int 8
        assert ent.loc[0, "uid"] == params_uid("DETECTORS", {
            "site": "north", "detector": "det_a", "calibration.channels": 8,
            "calibration.gain": 1.5, "calibration.offset": 0.25,
            "readout.temperature": 77.0})

    def test_the_location_keeps_sibling_entities_distinct(self, tmp_path):
        cfg = sites_dataset(tmp_path)
        del cfg["source"]["groups"]["params"]["location"]
        with pytest.raises(ValueError, match="4 entities share 2 uids"):
            run(tmp_path, cfg)

    def test_dotdot_resolves_against_each_entity_group(self, tmp_path):
        """'..' is the group that holds the entity group, '../..' the one above it, and a
        glob segment may stand between literal ones."""
        d = tmp_path / "campaigns"
        d.mkdir()
        with h5py.File(d / "c.h5", "w") as f:
            for c, flux in (("c1", 1.0), ("c2", 2.0), ("x9", 9.0)):
                f.create_dataset(f"{c}/flux", data=flux)
                f.create_dataset(f"{c}/scans/order", data=np.array([30, 10]))
                for s in ("s1", "s0"):
                    f.create_dataset(f"{c}/scans/{s}/image", data=np.zeros(2))
        cfg = {"label": "Campaigns", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "entity_group": "/c*/scans",
                                     "params": {"groups": {"campaign": "../..",
                                                           "scans": ".."}}}},
               "artifacts": [{"type": "image", "dataset": "image"}]}
        ent, _ = run(tmp_path, cfg)
        assert list(ent["source_group"]) == ["c1/scans/s0", "c1/scans/s1",
                                             "c2/scans/s0", "c2/scans/s1"]
        assert list(ent["campaign.flux"]) == [1.0, 1.0, 2.0, 2.0]
        assert list(ent["scans.order"]) == [30, 10, 30, 10]

    def test_a_sibling_array_gives_one_value_per_entity(self, tmp_path):
        ent, art = run(tmp_path, scans_dataset(tmp_path))
        assert list(ent["source_group"]) == [f"run/scan_{i:02d}" for i in range(1, 13)]
        assert list(ent.columns) == ["uid", "source_group", "beam_current", "energy",
                                     "mode", "beam_current_units"]
        assert list(ent["beam_current"]) == [i * 10.0 for i in range(12)]
        assert set(ent["energy"]) == {8.0} and set(ent["mode"]) == {3}
        assert set(ent["beam_current_units"]) == {"mA"}
        assert ent.loc[11, "uid"] == params_uid("SCANS", {
            "beam_current": 110.0, "energy": 8.0, "mode": 3})
        assert len(art) == 12

    def test_names_pair_with_elements_in_text_order_not_numeric(self, tmp_path):
        """The params description warns: scan_10 sorts before scan_2."""
        names = [f"scan_{i}" for i in range(1, 13)]
        ent, _ = run(tmp_path, scans_dataset(tmp_path, names=names))
        order = sorted(names)
        assert order[:4] == ["scan_1", "scan_10", "scan_11", "scan_12"]
        assert list(ent["source_group"]) == [f"run/{n}" for n in order]
        assert dict(zip(ent["source_group"], ent["beam_current"]))["run/scan_2"] == 40.0

    def test_siblings_are_counted_after_exclude_groups(self, tmp_path):
        """With 'calibration' not excluded there are 13 siblings, so the 12-element array
        is skipped, and 'calibration' is an entity itself."""
        cfg = scans_dataset(tmp_path, exclude=())
        cfg["artifacts"][0]["optional"] = True
        cfg["source"]["groups"]["identity"] = "provenance"
        ent, art = run(tmp_path, cfg)
        assert len(ent) == 13 and "run/calibration" in set(ent["source_group"])
        assert "beam_current" not in ent.columns and set(ent["energy"]) == {8.0}
        assert len(art) == 12

    def test_exclude_groups_applies_to_the_top_level_groups(self, tmp_path):
        cfg = groups_dataset(tmp_path)
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            for name in ("run_1", "run_2", "_meta", "Run_3"):
                f.create_dataset(f"{name}/spectrum", data=np.zeros(2))
                f.create_dataset(f"{name}/params/tenDq", data=float(len(name)))
        del cfg["source"]["groups"]["entity_group"]
        cfg["source"]["groups"]["exclude_groups"] = ["_*", "samp*", "run_[2-9]"]
        cfg["source"]["groups"]["identity"] = "provenance"
        ent, _ = run(tmp_path, cfg)
        assert list(ent["source_group"]) == ["Run_3", "run_1"]

    def test_attributes_beside_the_entity_groups_go_to_every_sibling(self, tmp_path):
        cfg = scans_dataset(tmp_path)
        with h5py.File(tmp_path / "scans" / "run.h5", "a") as f:
            f["run"].attrs["operator"] = "rm"
            f["run"].attrs["thresholds"] = np.arange(12.0)  # an attribute is never split
        cfg["source"]["groups"]["params"] = {"groups": {"run": ".."}, "from": "attrs"}
        cfg["source"]["groups"]["identity"] = "provenance"
        ent, _ = run(tmp_path, cfg)
        assert set(ent["run.operator"]) == {"rm"} and len(ent) == 12
        assert all(list(v) == list(np.arange(12.0)) for v in ent["run.thresholds"])

    # The YAMLs of the rounds-1-3 tests that recursed from '..' are contract errors now,
    # in tests/test_contract.py: test_recursive_takes_no_path_that_starts_with_dotdot.

    @pytest.mark.parametrize("south", [["det_a", "det_b"], ["det_a", "det_b", "det_c"]],
                             ids=["same-size", "other-size"])
    def test_recursing_above_the_matched_groups_reads_no_other_sets_array(self, tmp_path,
                                                                           south):
        """Each site's calibration holds one offset per detector of that site, in the
        order of that site's names. With 'recursive: true', '../..' read the other site's
        offsets too, and paired them with this site's detectors when the sizes agreed
        (review 2 of #21): the contract refuses it now. Named without 'recursive', as the
        Fix line says, '../calibration' gives element i to the site's own i-th detector,
        and '../..' reads the datasets of the root only."""
        d = tmp_path / "sites"
        d.mkdir()
        sets = {"north": (["det_a", "det_b"], 1.5, [0.25, 0.5]),
                "south": (south, 2.0, [0.1, 0.2, 0.3][:len(south)])}
        with h5py.File(d / "detectors.h5", "w") as f:
            f["beamline"] = 7
            for site, (detectors, gain, offsets) in sets.items():
                f[f"{site}/calibration/gain"] = gain
                f[f"{site}/calibration/offset"] = np.array(offsets)
                for k, det in enumerate(detectors):
                    f[f"{site}/{det}/temperature"] = 70.0 + k
                    f[f"{site}/{det}/spectrum"] = np.zeros(4)
        params = {"groups": {"top": "../..", "cal": "../calibration", "own": "/"},
                  "location": SITE_LOCATION}
        cfg = {"label": "Detectors", "metadata": dict(META),
               "source": {"groups": {
                   "directory": str(d), "entity_group": "/*",
                   "exclude_groups": ["calibration"],
                   "params": {**params, "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}
        with pytest.raises(ContractError, match=r"params\.groups\.top '\.\./\.\.' starts "
                                                r"with '\.\.', and 'recursive: true'"):
            run(tmp_path, cfg)
        cfg["source"]["groups"]["params"] = params
        ent, _ = run(tmp_path, cfg, name="named")
        assert set(ent.columns) == {"uid", "source_group", "site", "detector",
                                    "top.beamline", "cal.gain", "cal.offset",
                                    "own.temperature"}
        assert list(zip(ent["source_group"], ent["cal.offset"])) == [
            ("north/det_a", 0.25), ("north/det_b", 0.5),
            *zip((f"south/{n}" for n in south), sets["south"][2])]
        assert list(ent["cal.gain"]) == [1.5, 1.5] + [2.0] * len(south)
        assert ent.loc[1, "uid"] == params_uid("DETECTORS", {
            "site": "north", "detector": "det_b", "top.beamline": 7, "cal.gain": 1.5,
            "cal.offset": 0.5, "own.temperature": 71.0})

    @pytest.mark.parametrize("link, named", [
        ("peer", "outside the group being read"), ("copy", "an entity group of this"),
        ("far", "outside the group being read"), ("up", "outside the group being read"),
        ("into", "outside the group being read"), ("cal", "outside the group being read"),
    ])
    def test_recursion_inside_an_entity_group_follows_no_link_out_of_the_group(
            self, tmp_path, link, named, capsys):
        """ADR-0013: recursion follows only what lies inside the subtree of the group it
        reads, so it takes none of these links out of the entity group: 'peer' (a soft
        link to a sibling detector), 'far' (a soft link to another site), 'up' (a soft
        link back to its own site, which a walk that follows it never leaves), 'into' (a
        soft link into a subgroup of another detector: a leak of #34) and 'cal' (a soft
        link to another site's excluded group). 'copy' is a hard link, the one link that
        gives a group a second name inside this one, and it names another site's
        detector, an entity of the dataset, so the object-id set skips that one. A plain
        subgroup is read, and every skipped link is named."""
        d = tmp_path / "sites"
        d.mkdir()
        with h5py.File(d / "detectors.h5", "w") as f:
            for n, group in enumerate(["north/det_a", "north/det_b", "south/det_a"]):
                f[f"sites/{group}/temperature"] = 70.0 + n
                f[f"sites/{group}/spectrum"] = np.zeros(4)
                f[f"sites/{group}/local/gain"] = 0.5 + n / 10
            for site, gain in (("north", 1.5), ("south", 2.0)):
                f[f"sites/{site}/calibration/gain"] = gain
                f[f"sites/{site}/calibration/offsets"] = np.array([0.1, 0.2])
            f["sites/north/det_a"][link] = {
                "peer": h5py.SoftLink("/sites/north/det_b"), "copy": f["sites/south/det_a"],
                "far": h5py.SoftLink("/sites/south"), "up": h5py.SoftLink("/sites/north"),
                "into": h5py.SoftLink("/sites/south/det_a/local"),
                "cal": h5py.SoftLink("/sites/south/calibration"),
            }[link]
        cfg = {"label": "Detectors", "metadata": dict(META),
               "source": {"groups": {
                   "directory": str(d), "entity_group": "/sites/*",
                   "exclude_groups": ["calibration"],
                   "params": {"group": "/", "recursive": True,
                              "location": r"/(?P<site>[^/]+)/(?P<detector>[^/]+)$"}}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "source_group", "site", "detector",
                                    "temperature", "local.gain"}
        assert list(ent["temperature"]) == [70.0, 71.0, 72.0]
        assert list(ent["local.gain"]) == [0.5, 0.6, 0.7]
        assert f"detectors.h5:/sites/north/det_a/{link} links" in out and named in out

    def test_recursion_takes_no_external_link_out_of_the_file(self, tmp_path, capsys):
        """#34, as ADR-0013 settles it: an h5py.ExternalLink resolves in another file, so
        its target is never inside the subtree being read, and it is named and skipped
        whatever it points at -- another file's entity group, whose values would enter
        this entity's uid, and a group in a file the pattern does not match, which the
        rule before ADR-0013 read. Naming such a group under 'params.groups' still reads
        it."""
        d = tmp_path / "stations"
        d.mkdir()
        with h5py.File(d / "bench_calibration.h5", "w") as f:   # not matched by 'pattern'
            f["board/offset"] = 0.125
        with h5py.File(d / "station_b.h5", "w") as f:
            g = f.create_group("runs/night")
            g["temperature"] = 275.0
            g["readout/gain"] = 9.0
            g["spectrum"] = np.zeros(4)
        with h5py.File(d / "station_a.h5", "w") as f:
            g = f.create_group("runs/day")
            g["temperature"] = 300.0
            g["readout/gain"] = 3.0
            g["spectrum"] = np.zeros(4)
            g["other"] = h5py.ExternalLink("station_b.h5", "/runs/night")
            g["board"] = h5py.ExternalLink("bench_calibration.h5", "/board")
        cfg = {"label": "Stations Test", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "pattern": "station_*.h5",
                                     "entity_group": "/runs",
                                     "params": {"group": "/", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "source_group", "temperature", "readout.gain"}
        assert sorted(ent["temperature"]) == [275.0, 300.0]
        assert sorted(ent["readout.gain"]) == [3.0, 9.0]
        assert "station_a.h5:/runs/day/other links to" in out
        assert "station_b.h5:/runs/night, outside the group being read (/runs/day); " \
               "skipped" in out
        assert "station_a.h5:/runs/day/board links to" in out
        assert "bench_calibration.h5:/board, outside the group being read " \
               "(/runs/day); skipped" in out
        # the same group, named under 'params.groups', is read wherever the link leads
        with h5py.File(d / "station_b.h5", "a") as f:
            f["runs/night/board"] = h5py.ExternalLink("bench_calibration.h5", "/board")
        cfg["source"]["groups"]["params"] = {"groups": {"own": "/", "board": "/board"},
                                            "recursive": True}
        named, _ = run(tmp_path, cfg, name="named")
        assert sorted(named["board.offset"]) == [0.125, 0.125]
        assert sorted(named["own.temperature"]) == [275.0, 300.0]

    def test_a_dotdot_path_that_names_an_entity_group_is_read_by_the_sibling_rule(
            self, tmp_path):
        """A path that names a group is read as written, an entity group included, and by
        the rule of every group reached through '..': a scalar goes to every sibling, and
        a 1-D dataset of length N is split among them, so det_b takes element 1 of
        det_a's offsets (review 2 of #21)."""
        cfg = sites_dataset(tmp_path)
        with h5py.File(tmp_path / "sites" / "detectors.h5", "a") as f:
            for site, temperature, offsets in (("north", 70.0, [0.25, 0.5]),
                                               ("south", 72.0, [0.1, 0.2])):
                del f[f"{site}/det_a/temperature"]
                f[f"{site}/det_a/temperature"] = temperature
                f[f"{site}/det_a/offsets"] = np.array(offsets)
        cfg["source"]["groups"]["params"] = {"groups": {"ref": "../det_a"},
                                             "location": SITE_LOCATION}
        ent, _ = run(tmp_path, cfg)
        assert list(ent["source_group"]) == ["north/det_a", "north/det_b",
                                             "south/det_a", "south/det_c"]
        assert list(ent["ref.temperature"]) == [70.0, 70.0, 72.0, 72.0]
        assert list(ent["ref.offsets"]) == [0.25, 0.5, 0.1, 0.2]

    def test_recursing_above_a_branch_of_the_glob_is_refused(self, tmp_path):
        """Review 3 of #21: under '/run_*/scans', '../../..' with 'recursive: true' read
        each run's per-scan array beside its 'scans' group into the scans of the other
        run, split by their N. The contract refuses it before a file is read. Named
        without 'recursive', '../..' gives each scan its own run's element."""
        d = tmp_path / "runs"
        d.mkdir()
        with h5py.File(d / "runs.h5", "w") as f:
            for run_, energies in (("run_1", [8.0, 9.0]), ("run_2", [5.0, 6.0])):
                f[f"{run_}/scan_energy"] = np.array(energies)
                for scan in ("scan_01", "scan_02"):
                    f[f"{run_}/scans/{scan}/image"] = np.zeros(2)
        location = r":/(?P<run>[^/]+)/scans/(?P<scan>[^/]+)$"
        cfg = {"label": "Runs", "metadata": dict(META),
               "source": {"groups": {
                   "directory": str(d), "entity_group": "/run_*/scans",
                   "params": {"groups": {"up": "../../..", "own": "/"}, "recursive": True,
                              "location": location}}},
               "artifacts": [{"type": "image", "dataset": "image"}]}
        with pytest.raises(ContractError) as exc:
            run(tmp_path, cfg)
        assert str(exc.value).splitlines() == [
            "contract error: source.groups: params.groups.up '../../..' starts with '..', "
            "and 'recursive: true' is for paths inside the entity group only: from a group "
            "outside it the reader would reach values that belong to other entities",
            "Fix: name each group you need under params.groups, without recursive"]
        cfg["source"]["groups"]["params"] = {"groups": {"up": "../.."},
                                             "location": location}
        ent, _ = run(tmp_path, cfg, name="named")
        assert list(zip(ent["source_group"], ent["up.scan_energy"])) == [
            ("run_1/scans/scan_01", 8.0), ("run_1/scans/scan_02", 9.0),
            ("run_2/scans/scan_01", 5.0), ("run_2/scans/scan_02", 6.0)]

    def test_climbing_above_the_file_root_names_the_entity(self, tmp_path):
        cfg = scans_dataset(tmp_path)
        cfg["source"]["groups"]["params"] = {"groups": {"up": "../../../calibration"}}
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        assert str(exc.value) == (
            f"{tmp_path / 'scans' / 'run.h5'}:/run/scan_01: params.groups.up "
            "'../../../calibration' climbs 3 levels from an entity group 2 levels below the "
            "file root, so above the root; remove 1 '..'")

    def test_climbing_to_the_root_reads_the_root(self, tmp_path):
        cfg = scans_dataset(tmp_path)
        with h5py.File(tmp_path / "scans" / "run.h5", "a") as f:
            f.create_dataset("facility_code", data=7)
        cfg["source"]["groups"]["params"] = {"group": "../.."}
        cfg["source"]["groups"]["identity"] = "provenance"
        ent, _ = run(tmp_path, cfg)
        assert list(ent.columns) == ["uid", "source_group", "facility_code"]
        assert set(ent["facility_code"]) == {7} and len(ent) == 12

    @pytest.mark.parametrize("entity_group", ["/nothere", "/r?x/*", "/run/scan_[a-z]*"])
    def test_an_entity_group_that_matches_nothing_names_file_and_pattern(self, tmp_path,
                                                                         entity_group):
        cfg = scans_dataset(tmp_path)
        cfg["source"]["groups"]["entity_group"] = entity_group
        with pytest.raises(KeyError) as exc:
            run(tmp_path, cfg)
        assert exc.value.args[0] == (f"{tmp_path / 'scans' / 'run.h5'}: entity_group "
                                     f"'{entity_group}' matches no group")

    def test_a_glob_is_case_sensitive_and_skips_datasets(self, tmp_path):
        cfg = scans_dataset(tmp_path)
        cfg["source"]["groups"]["entity_group"] = "/R*"
        with pytest.raises(KeyError, match="matches no group"):
            run(tmp_path, cfg)
        cfg["source"]["groups"]["entity_group"] = "/run/beam*"  # a dataset, not a group
        with pytest.raises(KeyError, match="matches no group"):
            run(tmp_path, cfg, name="ds2")

    def test_excluding_every_subgroup_is_an_error(self, tmp_path):
        cfg = scans_dataset(tmp_path, exclude=("scan_*", "cal*"))
        with pytest.raises(ValueError, match=r"run\.h5: no groups under entity_group "
                                             r"'/run' to treat as entities \(after "
                                             r"exclude_groups\)"):
            run(tmp_path, cfg)

    def test_a_dotdot_group_is_read_once_per_sibling_set(self, tmp_path, monkeypatch):
        from tilewright import manifest

        reads = []
        real = manifest._read_group
        monkeypatch.setattr(manifest, "_read_group",
                            lambda holder, path, *a, **k: reads.append(path)
                            or real(holder, path, *a, **k))
        run(tmp_path, sites_dataset(tmp_path))
        assert reads.count("north/calibration") == 1
        assert reads.count("south/calibration") == 1
        assert len(reads) == 2 + 4  # and each detector's own group once

    # The two layouts of #11, in miniature, with the YAML of the decision comment
    # (https://github.com/slaclab/TileWright/issues/11#issuecomment-5712627796).

    def test_the_decision_for_osti_1972213(self, tmp_path):
        d = tmp_path / "geo"
        d.mkdir()
        fixed = {"coaxial": ["Pinj", "Tamb", "Tsurf", "cp_rock", "pipe_roughness", "rho_rock",
                             "area_ratio", "pipe_k", "pipe_thickness"],
                 "utube": ["Pinj", "Tamb", "Tsurf", "cp_rock", "pipe_roughness", "rho_rock"]}
        with h5py.File(d / "clgs_results_final.h5", "w") as f:
            for design, names in fixed.items():
                for k, name in enumerate(names):
                    f[f"{design}/fixed_params/{name}"] = float(k)
                for fluid in ("H2O", "sCO2"):
                    f[f"{design}/{fluid}/input/D"] = np.arange(3.0)
        yaml = YAML(typ="safe").load("""
            entity_group: "/*"
            exclude_groups: [fixed_params]
            params:
              groups: {design: ../fixed_params}
              location: '/(?P<design_name>[^/]+)/(?P<fluid>[^/]+)$'
        """)
        cfg = {"label": "GeoCLUSTER", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "pattern": "*.h5", **yaml}},
               "artifacts": [{"type": "h2o_D", "dataset": "input/D"}]}
        ent, art = run(tmp_path, cfg)
        assert list(zip(ent["design_name"], ent["fluid"])) == [
            ("coaxial", "H2O"), ("coaxial", "sCO2"), ("utube", "H2O"), ("utube", "sCO2")]
        assert ent["uid"].nunique() == 4 and len(art) == 4
        assert ent["design.pipe_k"].isna().tolist() == [False, False, True, True]
        assert list(ent["design.Pinj"]) == [0.0] * 4

    def test_the_decision_for_zenodo_3528199(self, tmp_path):
        d = tmp_path / "srct"
        d.mkdir()
        load = np.linspace(7.2, 1189.0, 11)
        with h5py.File(d / "NT4_T.hdf5", "w") as f:
            g = f.create_group("DataContainers/RawDataContainer_T")
            g["Load"], g["Displacement"] = load, np.linspace(0.0314, 0.3624, 11)
            for i in range(1, 12):
                g[f"step_{i:02d}/CellData/CellData"] = np.zeros((2, 2, 2), dtype="uint8")
        cfg = {"label": "X100", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "pattern": "NT4_T.hdf5",
                                     "entity_group": "/DataContainers/RawDataContainer_T",
                                     "params": {"group": ".."}}},
               "artifacts": [{"type": "volume", "dataset": "CellData/CellData"}]}
        ent, _ = run(tmp_path, cfg)
        assert list(ent.columns) == ["uid", "source_group", "Displacement", "Load"]
        assert list(ent["Load"]) == list(load) and len(ent) == 11
        assert ent.loc[3, "source_group"].endswith("/step_04")


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


def nexus_shape_one_dataset(tmp_path, identity):
    """Two scans whose scalars are all shape (1,): float, float32, int32, '|S' and vlen str."""
    d = tmp_path / "dmc"
    d.mkdir()
    for i, temp in enumerate((4.0017, 300.0)):
        with h5py.File(d / f"dmc{i + 1:02d}.h5", "w") as f:
            s = f.create_group("entry1/sample")
            s.create_dataset("sample_temperature", data=[temp]).attrs["units"] = "K"
            s.create_dataset("sample_name", data=np.array([b"Ga0.94Mn0.04Sb_8mm"]))
            s.create_dataset("comment", data=["powder, 8 mm can"], dtype=h5py.string_dtype())
            s.create_dataset("mass", data=0.5)
            m = f.create_group("entry1/monochromator")
            lam = m.create_dataset("lambda", data=np.array([2.5666], dtype="float32"))
            lam.attrs["units"] = "Angstrom"
            m.create_dataset("scan_index", data=np.array([i + 1], dtype="int32"))
            f.create_dataset("entry1/data/counts", data=np.arange(4) * i)
    return {"label": "DMC Test", "metadata": dict(META),
            "source": {"files": {"directory": str(d), "pattern": "*.h5", "identity": identity,
                                 "params": {"groups": {"sample": "/entry1/sample",
                                                       "monochromator": "/entry1/monochromator"}}}},
            "artifacts": [{"type": "counts", "dataset": "/entry1/data/counts"}]}


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

    @pytest.mark.parametrize("identity", ["params", "provenance"])
    def test_shape_one_scalars_are_parameters(self, tmp_path, identity):
        # SINQ DMC-style NeXus: every scalar is a length-1 array, none is 0-dim (#4)
        ent, _ = run(tmp_path, nexus_shape_one_dataset(tmp_path, identity))
        assert len(ent) == 2 and ent["uid"].nunique() == 2
        row = ent.sort_values("sample.sample_temperature").iloc[0]
        assert row["sample.sample_temperature"] == 4.0017
        assert row["sample.sample_temperature_units"] == "K"
        assert row["sample.sample_name"] == "Ga0.94Mn0.04Sb_8mm"  # decoded, not bytes
        assert row["sample.comment"] == "powder, 8 mm can"
        assert row["sample.mass"] == 0.5  # a 0-dim dataset beside them
        assert row["monochromator.lambda"] == pytest.approx(2.5666)
        assert row["monochromator.lambda_units"] == "Angstrom"
        assert row["monochromator.scan_index"] == 1

    def test_a_link_back_to_an_ancestor_is_named_and_skipped(self, tmp_path, capsys):
        """#29: a link to a group already on the path being read sends the walk round
        sub/up/sub/up without end. It is named and skipped; the rest of the group is read."""
        d = tmp_path / "cycle"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            entry = f.create_group("entry")
            entry["temperature"] = 300.0
            entry["sub/gain"] = 7
            entry["sub/up"] = h5py.SoftLink("/entry")
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Cycle Test", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/entry", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        assert set(ent.columns) == {"uid", "temperature", "sub.gain"}
        assert ent.loc[0, "temperature"] == 300.0 and ent.loc[0, "sub.gain"] == 7
        out = capsys.readouterr().out
        assert "WARNING" in out and ("run_0.h5:/entry/sub/up links back to /entry, which "
                                     "is already being read; skipped") in out

    def test_a_link_cycle_in_the_params_group_is_named_and_skipped(self, tmp_path, capsys):
        """#40: two members that link to each other make a chain longer than HDF5 will
        follow, and it refuses to resolve either. That is a RuntimeError, not the KeyError
        a dangling link raises, so it escaped and killed the command with a traceback
        naming no file and no member. It is now named and skipped, as the dangling link
        beside it is, and the rest of the group is read."""
        d = tmp_path / "linkcycle"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            meta = f.create_group("meta")
            meta["temperature"] = 300.0
            meta["sub/gain"] = 7
            meta["a"] = h5py.SoftLink("/meta/b")
            meta["b"] = h5py.SoftLink("/meta/a")
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Link Cycle Test", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/meta", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        assert set(ent.columns) == {"uid", "temperature", "sub.gain"}
        assert ent.loc[0, "temperature"] == 300.0 and ent.loc[0, "sub.gain"] == 7
        out = capsys.readouterr().out
        for member in ("a", "b"):
            assert f"{d / 'run_0.h5'}:/meta/{member} unreadable" in out, out
        assert out.count("skipped") == 2

    def test_one_group_linked_twice_beside_the_path_is_read_under_both_names(self, tmp_path):
        """#29: only the groups on the current path are skipped. A file that holds one
        group under two names is read under both, and keeps the uid it had before the
        cycle rule; a global 'visited' set would read it once and change that uid."""
        d = tmp_path / "twice"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            entry = f.create_group("entry")
            entry["temperature"] = 300.0
            entry["calibration/gain"] = 1.5
            entry["again"] = entry["calibration"]   # a second hard link to the one group
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Twice Test", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/entry", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        ent, _ = run(tmp_path, cfg)
        assert set(ent.columns) == {"uid", "temperature", "calibration.gain", "again.gain"}
        assert ent.loc[0, "calibration.gain"] == 1.5 and ent.loc[0, "again.gain"] == 1.5
        assert ent.loc[0, "uid"] == "23e18e1dc8739b6d"   # what main gave this file

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

class TestRecursionStaysInTheSubtree:
    """ADR-0013: with 'recursive: true' the walk follows only what lies inside the params
    group's own subtree, whatever the source tag. The three cases below are the leaks the
    iteration-11 review of #34 found, each on a miniature of the file it was found on."""

    def stations(self, tmp_path, link):
        """Two station files, one entity group per station ('day' in station_a, 'night'
        in station_b), and one link from day's entity group as the case needs it."""
        d = tmp_path / "stations"
        d.mkdir()
        with h5py.File(d / "station_b.h5", "w") as f:
            g = f.create_group("runs/night")
            g["temperature"] = 275.0
            g["readout/gain"] = 9.0
            g["spectrum"] = np.zeros(4)
        with h5py.File(d / "station_a.h5", "w") as f:
            g = f.create_group("runs/day")
            g["temperature"] = 300.0
            g["readout/gain"] = 3.0
            g["spectrum"] = np.zeros(4)
            if link is not None:
                g["peek"] = link
        return {"label": "Stations", "metadata": dict(META),
                "source": {"groups": {"directory": str(d), "pattern": "station_*.h5",
                                      "entity_group": "/runs",
                                      "params": {"group": "/", "recursive": True}}},
                "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}

    def test_a_soft_link_into_a_sibling_entity_groups_subgroup_is_named_and_skipped(
            self, tmp_path, capsys):
        """The first leak: a soft link inside one entity group that names a *subgroup* of
        a sibling entity group in the same file. The sibling entity group itself was
        skipped, its subgroups were not, so 'day' took 'night''s gain into its uid."""
        d = tmp_path / "one_station"
        d.mkdir()
        with h5py.File(d / "station_a.h5", "w") as f:
            for name, temperature, gain in (("day", 300.0, 3.0), ("night", 275.0, 9.0)):
                g = f.create_group(f"runs/{name}")
                g["temperature"] = temperature
                g["readout/gain"] = gain
                g["spectrum"] = np.zeros(4)
            f["runs/day/peek"] = h5py.SoftLink("/runs/night/readout")
        cfg = {"label": "One Station", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "pattern": "station_*.h5",
                                     "entity_group": "/runs",
                                     "params": {"group": "/", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "source_group", "temperature", "readout.gain"}
        assert "peek.gain" not in ent.columns
        assert ("station_a.h5:/runs/day/peek links to" in out
                and "station_a.h5:/runs/night/readout, outside the group being read "
                    "(/runs/day); skipped" in out)

    def test_an_external_link_into_another_files_entity_group_is_named_and_skipped(
            self, tmp_path, capsys):
        """The second leak: the same link across files, into a subgroup of the entity
        group of another file of the dataset. Its value entered the uid."""
        cfg = self.stations(tmp_path, h5py.ExternalLink("station_b.h5", "/runs/night/readout"))
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "source_group", "temperature", "readout.gain"}
        assert sorted(ent["readout.gain"]) == [3.0, 9.0]        # each its own
        assert ("station_a.h5:/runs/day/peek links to" in out
                and "station_b.h5:/runs/night/readout, outside the group being read "
                    "(/runs/day); skipped" in out)

    def test_a_files_params_group_takes_no_link_into_another_file(self, tmp_path, capsys):
        """The third leak: a 'files' source had no skip set at all, so a link from one
        file's params group into another file of the dataset pulled that file's
        parameters into this entity's uid. The rule holds for every source tag."""
        d = tmp_path / "runs"
        d.mkdir()
        with h5py.File(d / "run_1.h5", "w") as f:
            f["entry/temperature"] = 275.0
            f["entry/sub/gain"] = 9.0
            f["spectrum"] = np.zeros(4)
        with h5py.File(d / "run_0.h5", "w") as f:
            f["entry/temperature"] = 300.0
            f["entry/sub/gain"] = 3.0
            f["spectrum"] = np.zeros(4)
            f["entry/peer"] = h5py.ExternalLink("run_1.h5", "/entry")
        cfg = {"label": "Runs", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/entry", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "temperature", "sub.gain"}
        assert sorted(ent["temperature"]) == [275.0, 300.0]
        assert ("run_0.h5:/entry/peer links to" in out
                and "run_1.h5:/entry, outside the group being read (/entry); skipped" in out)

    def test_a_link_inside_the_subtree_is_read(self, tmp_path, capsys):
        """The positive case: a soft link is followed when its target is inside the group
        being read, and the group it names is read under the link's own name. A link that
        names the group being read itself is the #29 case, and stops the walk there."""
        d = tmp_path / "inside"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            f["entry/temperature"] = 300.0
            f["entry/detector/gain"] = 7.0
            f["entry/alias"] = h5py.SoftLink("/entry/detector")     # inside, absolute
            f["entry/relative"] = h5py.SoftLink("detector")         # inside, relative
            f["entry/detector/up"] = h5py.SoftLink("/entry")        # the #29 case
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Inside", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/entry", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "temperature", "detector.gain", "alias.gain",
                                    "relative.gain"}
        assert ent.loc[0, "alias.gain"] == 7.0 and ent.loc[0, "relative.gain"] == 7.0
        assert "outside the group being read" not in out
        assert "run_0.h5:/entry/detector/up links back to /entry, which is already " \
               "being read; skipped" in out

    def test_a_chain_of_links_out_of_the_subtree_is_named_and_skipped(self, tmp_path, capsys):
        """A link to a link: testing one link's own target places 'hop' inside the group,
        because '/entry/direct' is, and the walk then descends into what 'direct' names.
        The chain is followed to its final target, and each member is named once."""
        d = tmp_path / "chain"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            f["entry/temperature"] = 300.0
            f["elsewhere/gain"] = 99.0                        # outside /entry
            f["entry/direct"] = h5py.SoftLink("/elsewhere")   # one link out
            f["entry/hop"] = h5py.SoftLink("/entry/direct")   # two
            f["entry/hop3"] = h5py.SoftLink("/entry/hop")     # three
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Chain", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/entry", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "temperature"}
        for name in ("direct", "hop", "hop3"):
            assert f"run_0.h5:/entry/{name} links to" in out
        assert out.count("run_0.h5:/elsewhere, outside the group being "
                         "read (/entry); skipped") == 3

    def test_a_chain_out_of_the_subtree_is_skipped_under_groups(self, tmp_path, capsys):
        """The same chain under 'groups', where the group the author named lies inside the
        entity group: 'hop3 -> hop -> mid -> /secret/vault' gave 'day' the vault's gain."""
        d = tmp_path / "chain_groups"
        d.mkdir()
        with h5py.File(d / "station_a.h5", "w") as f:
            f["secret/vault/gain"] = 99.0
            for name, gain in (("day", 3.0), ("night", 9.0)):
                g = f.create_group(f"runs/{name}")
                g["readout/gain"] = gain
                g["spectrum"] = np.zeros(4)
            f["runs/day/readout/mid"] = h5py.SoftLink("/secret/vault")
            f["runs/day/readout/hop"] = h5py.SoftLink("/runs/day/readout/mid")
            f["runs/day/readout/hop3"] = h5py.SoftLink("/runs/day/readout/hop")
        cfg = {"label": "Chain Groups", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "pattern": "station_*.h5",
                                     "entity_group": "/runs",
                                     "params": {"group": "readout", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "source_group", "gain"}
        assert sorted(ent["gain"]) == [3.0, 9.0]
        assert out.count("station_a.h5:/secret/vault, outside the group being "
                         "read (/runs/day/readout); skipped") == 3

    def test_a_chain_out_of_the_subtree_is_skipped_under_batch(self, tmp_path, capsys):
        """And under 'batch', where the params group is read once for every row of a file:
        the chain put the outside value in every row."""
        cfg = batch_dataset(tmp_path)
        cfg["source"]["batch"]["params"]["recursive"] = True
        with h5py.File(tmp_path / "sim" / "batch_0" / "sim.h5", "a") as f:
            f["outside/v"] = 9.0
            f["params/mid"] = h5py.SoftLink("/outside")
            f["params/hop"] = h5py.SoftLink("/params/mid")
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "alpha", "beta", "seed"}
        assert out.count("sim.h5:/outside, outside the group being read (/params); "
                         "skipped") == 2

    def test_a_link_in_the_middle_of_the_target_path_is_named_and_skipped(
            self, tmp_path, capsys):
        """A target path is not evidence that a member is inside: any component of it can
        be a link. '/entry/sub/hop -> /entry/out/gain' starts with '/entry', but 'out' is
        itself a link to '/elsewhere', so resolving the target's parent in one step lands
        outside without the link that led there ever being tested. Dataset and subgroup
        alike, and the group skipped under one name must not be read under another."""
        d = tmp_path / "through"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            f["entry/temperature"] = 300.0
            f["elsewhere/gain"] = 99.0
            f["elsewhere/box/deep"] = 88.0
            f["entry/out"] = h5py.SoftLink("/elsewhere")            # direct member
            f["entry/sub/own"] = 1.0
            f["entry/sub/hop"] = h5py.SoftLink("/entry/out/gain")   # a dataset, through it
            f["entry/sub/hopg"] = h5py.SoftLink("/entry/out/box")   # a group, through it
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Through", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/entry", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "temperature", "sub.own"}
        for name in ("out", "sub/hop", "sub/hopg"):
            assert f"run_0.h5:/entry/{name} links to" in out
        assert out.count("run_0.h5:/elsewhere, outside the group being read (/entry); "
                         "skipped") == 3

    def test_a_link_in_the_middle_is_skipped_under_a_globbed_entity_group(
            self, tmp_path, capsys):
        """The same shape under 'groups' with a globbed 'entity_group', where the path
        runs through a link into a *sibling entity's* own params group: 'det1' took
        'det2''s value, under a key of its own, with no message."""
        d = tmp_path / "sites"
        d.mkdir()
        with h5py.File(d / "site_a.h5", "w") as f:
            for name, own in (("det1", 1.0), ("det2", 7.0)):
                g = f.create_group(f"siteA/{name}")
                g["readout/own"] = own
                g["spectrum"] = np.zeros(4)
            f["siteA/det1/readout/out"] = h5py.SoftLink("/siteA/det2/readout")
            f["siteA/det1/readout/sub/hop"] = h5py.SoftLink("/siteA/det1/readout/out/own")
        cfg = {"label": "Sites", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "pattern": "site_*.h5",
                                     "entity_group": "/*",
                                     "params": {"group": "readout", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "source_group", "own"}
        assert sorted(ent["own"]) == [1.0, 7.0]
        assert out.count("site_a.h5:/siteA/det2/readout, outside the group being read "
                         "(/siteA/det1/readout); skipped") == 2

    def test_a_link_in_the_middle_of_the_target_path_is_skipped_under_batch(
            self, tmp_path, capsys):
        """And under 'batch', where it reached every row of the file."""
        cfg = batch_dataset(tmp_path)
        cfg["source"]["batch"]["params"]["recursive"] = True
        with h5py.File(tmp_path / "sim" / "batch_0" / "sim.h5", "a") as f:
            f["outside/v"] = 9.0
            f["params/out"] = h5py.SoftLink("/outside")
            f["params/sub/hop"] = h5py.SoftLink("/params/out/v")
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "alpha", "beta", "seed"}
        assert out.count("sim.h5:/outside, outside the group being read (/params); "
                         "skipped") == 2

    def test_an_external_link_in_the_middle_of_the_target_path_is_named_and_skipped(
            self, tmp_path, capsys):
        """The cross-file half of the same case: '/entry/ext' is an external link, so
        '/entry/sub/thru -> /entry/ext/inner' names a path that leaves the file although
        its text does not. The object HDF5 resolves it to lives in a file the 'pattern'
        does not match, which the file of the resolved object settles whatever the path
        text says."""
        d = tmp_path / "vault"
        d.mkdir()
        with h5py.File(d / "other.h5", "w") as o:     # 'pattern' does not match it
            o["vault/inner"] = 55.0
            o["vault/box/deep"] = 66.0
        with h5py.File(d / "run_0.h5", "w") as f:
            f["entry/temperature"] = 300.0
            f["entry/sub/own"] = 1.0
            f["entry/ext"] = h5py.ExternalLink("other.h5", "/vault")
            f["entry/sub/thru"] = h5py.SoftLink("/entry/ext/inner")
            f["entry/sub/thrug"] = h5py.SoftLink("/entry/ext/box")
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Vault", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "run_*.h5",
                                    "params": {"group": "/entry", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "temperature", "sub.own"}
        for name in ("ext", "sub/thru", "sub/thrug"):
            assert f"run_0.h5:/entry/{name} links to" in out
        assert out.count("other.h5:/vault, outside the group being read (/entry); "
                         "skipped") == 3
        assert "other.h5:/entry" not in out       # never the target file with a local path

    def test_a_deep_path_inside_the_subtree_is_still_read(self, tmp_path, capsys):
        """The guard on the other side: walking the target component by component must not
        turn a legitimate path inside the subtree into a skip, however deep it is and
        however many links inside the subtree it goes through."""
        d = tmp_path / "deep"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            f["entry/temperature"] = 300.0
            f["entry/a/b/c/d/e/deep"] = 5.0
            f["entry/mid"] = h5py.SoftLink("/entry/a/b")                  # inside
            f["entry/sub/far"] = h5py.SoftLink("/entry/mid/c/d/e/deep")   # through it
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Deep", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/entry", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert ent.loc[0, "sub.far"] == 5.0 and ent.loc[0, "a.b.c.d.e.deep"] == 5.0
        assert ent.loc[0, "mid.c.d.e.deep"] == 5.0
        assert "outside the group being read" not in out

    def test_the_file_of_the_resolved_object_settles_it_whatever_the_path_says(
            self, tmp_path):
        """The second guard, on its own. It stands behind the walk -- an external link is
        the only way to an object in another file, and the walk names that link first and
        more precisely -- so it is tested here directly: an object in another file is
        outside however its own name reads, and its file is what is reported."""
        d = tmp_path / "guard"
        d.mkdir()
        with h5py.File(d / "other.h5", "w") as o:
            o["vault/inner"] = 55.0
        with h5py.File(d / "run_0.h5", "w") as f:
            f["entry/own"] = 1.0
        with h5py.File(d / "run_0.h5", "r") as f, h5py.File(d / "other.h5", "r") as o:
            g = f["/entry"]
            assert _outside(g, "own", g["own"], (g, "/entry")) is None
            assert _outside(g, "own", o["vault/inner"], (g, "/entry")) == str(d / "other.h5")

    def test_a_linked_dataset_below_the_group_is_named_and_skipped(self, tmp_path, capsys):
        """Recursion holds for datasets as well as subgroups. Below the group the author
        named, a dataset link out of the subtree took a sibling entity's own value, and a
        value from a file the 'pattern' does not match, into this entity's uid."""
        d = tmp_path / "station"
        d.mkdir()
        with h5py.File(d / "calibration.dat", "w") as f:   # 'pattern' does not match it
            f["vault/secret"] = 55.0
        with h5py.File(d / "station_a.h5", "w") as f:
            for name, temperature in (("day", 300.0), ("night", 275.0)):
                g = f.create_group(f"runs/{name}")
                g["temperature"] = temperature
                g["sub/own"] = 1.0
                g["spectrum"] = np.zeros(4)
            f["runs/day/sub/borrowed"] = h5py.SoftLink("/runs/night/temperature")
            f["runs/day/sub/fromfile"] = h5py.ExternalLink("calibration.dat", "/vault/secret")
        cfg = {"label": "Station", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "pattern": "station_*.h5",
                                     "entity_group": "/runs",
                                     "params": {"group": "/", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "source_group", "temperature", "sub.own"}
        assert ("station_a.h5:/runs/day/sub/borrowed links to" in out
                and "station_a.h5:/runs/night/temperature, outside the group being read "
                    "(/runs/day); skipped" in out)
        assert ("station_a.h5:/runs/day/sub/fromfile links to" in out
                and "calibration.dat:/vault/secret, outside the group being read "
                    "(/runs/day); skipped" in out)

    def test_a_member_of_the_group_itself_is_read_wherever_its_link_leads(
            self, tmp_path, capsys):
        """The other half of the rule: the group the author named is read as it is without
        'recursive', so a dataset link written in that group is followed wherever it points
        -- turning 'recursive' on must not take away a column the author asked for. Below
        it the same link is skipped (the test above)."""
        d = tmp_path / "member"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            f["entry/temperature"] = 300.0
            f["elsewhere/gain"] = 99.0
            f["entry/borrowed"] = h5py.SoftLink("/elsewhere/gain")   # a dataset, not a group
            f["entry/sub/own"] = 1.0
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Member", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/entry", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "temperature", "borrowed", "sub.own"}
        assert ent.loc[0, "borrowed"] == 99.0
        assert "outside the group being read" not in out

    def test_a_soft_link_to_an_external_link_names_that_links_own_file_and_path(
            self, tmp_path, capsys):
        """The warning must name a location that exists. A soft link whose target is an
        external link was reported as the target file paired with the path in the source
        file ('cal.dat:/meta/extg'); the chain places it at the external link's own file
        and its own path."""
        d = tmp_path / "meta"
        d.mkdir()
        with h5py.File(d / "cal.dat", "w") as f:     # 'pattern' does not match it
            f["store/gain"] = 5.0
        with h5py.File(d / "run_0.h5", "w") as f:
            f["meta/temperature"] = 300.0
            f["meta/extg"] = h5py.ExternalLink("cal.dat", "/store")
            f["meta/hopext"] = h5py.SoftLink("/meta/extg")
            f["spectrum"] = np.zeros(4)
        cfg = {"label": "Meta", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "params": {"group": "/meta", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert set(ent.columns) == {"uid", "temperature"}
        assert "run_0.h5:/meta/hopext links to" in out
        assert out.count("cal.dat:/store, outside the group being read (/meta); "
                         "skipped") == 2
        assert "cal.dat:/meta/extg" not in out

    def test_a_hard_link_into_a_sibling_entity_groups_subgroup_is_read(self, tmp_path):
        """The residual case ADR-0013 records. A hard link is one of the object's own
        names, so a second name for a *subgroup* of a sibling entity group is a member of
        this entity group like any other and is read: 'closed' holds the entity groups and
        the matched groups, not what is inside them, and the reference-count rule that
        would catch it lost (it drops a group an author gave two names on purpose)."""
        d = tmp_path / "sites"
        d.mkdir()
        with h5py.File(d / "site_a.h5", "w") as f:
            for name, own in (("det1", 40.0), ("det2", 41.0)):
                g = f.create_group(f"siteA/{name}")
                g["readout/own"] = own
                g["spectrum"] = np.zeros(4)
            f["siteA/det1/readout/hardpeek"] = f["siteA/det2/readout"]
        cfg = {"label": "Sites", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "pattern": "site_*.h5",
                                     "entity_group": "/*",
                                     "params": {"group": "/", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        row = ent[ent["source_group"] == "siteA/det1"].iloc[0]
        assert row["readout.hardpeek.own"] == 41.0 and row["readout.own"] == 40.0

    def test_a_target_path_running_through_a_skipped_hard_link_is_followed(
            self, tmp_path, capsys):
        """The third residual ADR-0013 records. 'closed' decides a member's own name, not
        the components of a target path inside '_outside's walk. So a name that resolves
        to the sibling entity group is warned about and skipped whether it is the hard
        link itself or a soft link to it, while a soft link whose target path merely runs
        *through* that name reaches the sibling's values and carries them into this
        entity's parameters, and so into its uid."""
        d = tmp_path / "sites"
        d.mkdir()
        with h5py.File(d / "site_a.h5", "w") as f:
            for name, temp, own in (("det1", 300.0, 1.0), ("det2", 7.0, 2.0)):
                g = f.create_group(f"siteA/{name}")
                g["readout/temperature"] = temp
                g["readout/sub/own"] = own
                g["spectrum"] = np.zeros(4)
            f["siteA/det1/readout/hardsib"] = f["siteA/det2"]
            f["siteA/det1/readout/sub/hop"] = h5py.SoftLink(
                "/siteA/det1/readout/hardsib/readout/temperature")
            f["siteA/det1/readout/sub/hopent"] = h5py.SoftLink(
                "/siteA/det1/readout/hardsib")
        cfg = {"label": "Sites", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "pattern": "site_*.h5",
                                     "entity_group": "/*",
                                     "params": {"group": "readout", "recursive": True}}},
               "artifacts": [{"type": "spectrum", "dataset": "spectrum"}]}
        capsys.readouterr()
        with stops_within(30):
            ent, _ = run(tmp_path, cfg)
        out = capsys.readouterr().out
        # the two names that resolve to the sibling entity group: both skipped
        for name in ("hardsib", "sub/hopent"):
            assert (f"site_a.h5:/siteA/det1/readout/{name} links into /siteA/det2, an "
                    f"entity group of this dataset; skipped") in out
        # the path that only runs through one of them: followed, values and all
        row = ent[ent["source_group"] == "siteA/det1"].iloc[0]
        assert row["sub.hop"] == 7.0 and row["temperature"] == 300.0
        assert not [c for c in ent.columns if "hopent" in c]


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

    def test_epoch_seconds_a_millisecond_apart_stay_distinct(self, tmp_path):
        # review of #15: at 12 significant digits these three were one entity
        d = tmp_path / "epoch"
        d.mkdir()
        for i, t in enumerate(EPOCHS):
            with h5py.File(d / f"shot_{i}.h5", "w") as f:
                f.create_dataset("start_epoch", data=t)
                f.create_dataset("signal", data=np.full((2, 3), i, dtype="float32"))
        cfg = {"label": "Epoch Test", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5"}},
               "artifacts": [{"type": "signal", "dataset": "/signal"}]}
        ent, _ = run(tmp_path, cfg)
        assert len(ent) == 3 and ent["uid"].nunique() == 3
        assert sorted(ent["start_epoch"]) == EPOCHS

    def test_floats_keep_12_decimals_or_12_significant_digits_whichever_is_finer(self):
        def uid(**params):
            return _params_uid("K", params)
        # below 0.1, 12 significant digits: SI-scale values stay apart (#4) ...
        assert len({uid(time=t) for t in (*SI_TIMES, 0.0)}) == 4
        assert uid(charge=1.602176634e-19) != uid(charge=1.602176635e-19)
        assert uid(x=0.05) != uid(x=0.05 + 1e-13)
        # ... and noise past the 12th significant digit is not a new entity
        assert uid(time=SI_TIMES[0]) == uid(time=SI_TIMES[0] * (1 + 1e-14))
        assert uid(x=0.05) == uid(x=0.05 + 1e-14)
        # from 0.1 up, 12 decimal places: large values keep more than 12 significant
        # digits (review of #15) ...
        assert len({uid(start_epoch=t) for t in EPOCHS}) == 3
        assert uid(T=300.0) != uid(T=300.0 + 1e-11)
        # ... and noise past the 12th decimal place is not a new entity
        assert uid(T=300.0) == uid(T=300.0 + 1e-13)
        assert uid(x=0.1 + 0.2) == uid(x=0.3)
        # values with few digits hash exactly as they did before the change (b268731)
        assert uid(T=300.0, run=1) == "2c4f3c84c370721c"
        assert uid(T=2.5666, label="x") == "75c8ab85fd63385c"

    def test_from_one_tenth_up_a_float_hashes_as_before(self):
        # for |v| >= 0.1 the uid is b268731's round(v, 12) one, so no entity there is re-keyed
        spread = [s * m * 10.0 ** e for e in range(-1, 25) for s in (1, -1)
                  for m in (1.0, 1.2345678901234567, 2.5666000843048096, 9.87654321098765)]
        spread += [0.30000000000000004, 300.0 + 1e-11, *EPOCHS, 2.0 ** 53 + 1, 1e300]
        for v in spread:
            assert abs(v) >= 0.1
            assert _params_uid("K", {"v": v}) == uid_b268731("K", {"v": v}), v

    @pytest.mark.parametrize("v, before", [
        (0.0, "a02a0ed3ce898350"), (-0.0, "f0ce25eb9bfa02e4"), (math.nan, "4195f82f3070bfe8"),
        (math.inf, "6495de52e625a37b"), (-math.inf, "a18546143a0efd8e"),
    ])
    def test_zero_and_non_finite_floats_hash_as_before(self, v, before):
        # the literals are b268731's uids; -0.0 stays apart from 0.0, as it was
        assert _params_uid("K", {"x": v}) == uid_b268731("K", {"x": v}) == before


SI_TIMES = [8.390153e-14, 1.007e-13, 1.316102e-13]
SI_DT = 3.290256e-16
EPOCHS = [1726560000.000, 1726560000.001, 1726560000.002]


def uid_b268731(key, params):
    """The uid as b268731 (before #4) computed it: every float rounded to 12 decimal places."""
    canonical = {k: round(v, 12) if isinstance(v, float) else v for k, v in sorted(params.items())}
    return sha16(json.dumps({"ns": key, "params": canonical}, sort_keys=True, default=str))


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


def params_uid(key, params):
    return sha16(json.dumps({"ns": key, "params": params}, sort_keys=True))


def bci_dataset(tmp_path):
    """Like osti/1414275: year and month only in the file name, nothing to tell the files
    apart inside (every file holds the same measurement height)."""
    d = tmp_path / "bci"
    for year, month in ((2010, "DEC"), (2011, "APR"), (2011, "MAY")):
        (d / str(year)).mkdir(parents=True, exist_ok=True)
        with h5py.File(d / str(year) / f"BCI_{year}{month}.h5", "w") as f:
            f.create_dataset("hgt", data=50.0)
            f.create_dataset("tmp", data=np.zeros((1, 1, 4)))
    return {"label": "BCI", "metadata": dict(META),
            "source": {"files": {"directory": str(d), "pattern": "*/BCI_*.h5", "params": {
                "location": r"BCI_(?P<year>\d{4})(?P<month>[A-Z]{3})\.h5$"}}},
            "artifacts": [{"type": "tmp", "dataset": "/tmp"}]}


class TestLocation:
    """params.location (ADR-0010): values that only the path, group name or row holds."""

    def test_files_year_and_month_from_the_file_name(self, tmp_path):
        ent, art = run(tmp_path, bci_dataset(tmp_path))
        assert list(ent.columns) == ["uid", "year", "month", "hgt"]
        assert list(zip(ent["year"], ent["month"])) == [(2010, "DEC"), (2011, "APR"),
                                                        (2011, "MAY")]
        assert pd.api.types.is_integer_dtype(ent["year"])
        assert pd.api.types.is_string_dtype(ent["month"])
        assert ent.loc[1, "uid"] == params_uid("BCI", {"year": 2011, "month": "APR",
                                                       "hgt": 50.0})
        assert list(art["file"]) == ["2010/BCI_2010DEC.h5", "2011/BCI_2011APR.h5",
                                     "2011/BCI_2011MAY.h5"]

    def test_files_location_is_the_relative_path_with_slashes(self, tmp_path):
        cfg = bci_dataset(tmp_path)
        cfg["source"]["files"]["params"]["location"] = r"^(?P<folder>\d{4})/BCI_\d{4}"
        cfg["source"]["files"]["params"]["exclude"] = ["/hgt"]
        cfg["source"]["files"]["identity"] = "provenance"
        ent, _ = run(tmp_path, cfg)
        assert list(ent.columns) == ["uid", "folder"]
        assert list(ent["folder"]) == [2010, 2011, 2011]

    def test_unnamed_groups_are_wildcards(self, tmp_path):
        cfg = bci_dataset(tmp_path)
        cfg["source"]["files"]["params"]["location"] = r"(\d{4})/BCI_(\d{4})(?P<month>\w+)\."
        ent, _ = run(tmp_path, cfg)
        assert list(ent.columns) == ["uid", "month", "hgt"]
        assert list(ent["month"]) == ["DEC", "APR", "MAY"]

    def test_a_group_outside_the_match_is_null(self, tmp_path):
        cfg = bci_dataset(tmp_path)
        cfg["source"]["files"]["params"]["location"] = (
            r"BCI_(?P<year>\d{4})(?:(?P<may>MAY)|[A-Z]{3})\.h5$")
        cfg["source"]["files"]["identity"] = "provenance"
        ent, _ = run(tmp_path, cfg)
        assert ent["may"].isna().tolist() == [True, True, False]
        assert ent.loc[2, "may"] == "MAY"

    def test_groups_capture_the_group_name(self, tmp_path):
        cfg = groups_dataset(tmp_path)
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            for i in range(3):
                f[f"samples/sample_{i}/params/tenDq"][...] = 1.5
        cfg["source"]["groups"]["params"]["location"] = (
            r"^(?P<file>\w+)\.h5:/samples/sample_(?P<sample>\d+)$")
        ent, _ = run(tmp_path, cfg)
        assert list(ent.columns) == ["uid", "source_group", "file", "sample", "tenDq"]
        assert list(ent["sample"]) == [0, 1, 2] and set(ent["file"]) == {"samples"}
        assert ent["uid"].nunique() == 3
        assert ent.loc[2, "uid"] == params_uid("GROUPS_TEST", {"file": "samples",
                                                               "sample": 2, "tenDq": 1.5})

    def test_batch_row_number_makes_rows_distinct(self, tmp_path):
        """Like osti/1787546: nothing but the row tells the rows of a file apart."""
        cfg = batch_dataset(tmp_path)
        for b in range(2):
            with h5py.File(tmp_path / "sim" / f"batch_{b}" / "sim.h5", "a") as f:
                del f["params/alpha"], f["params/beta"]
        with pytest.raises(ValueError, match="6 entities share 2 uids"):
            run(tmp_path, cfg)
        cfg["source"]["batch"]["params"]["location"] = r":(?P<row>\d+)$"
        ent, art = run(tmp_path, cfg, name="ds2")
        assert list(ent.columns) == ["uid", "row", "seed"]
        assert list(zip(ent["seed"], ent["row"])) == [(0, 0), (0, 1), (0, 2),
                                                      (1, 0), (1, 1), (1, 2)]
        assert list(ent["uid"]) == [params_uid("BATCH_TEST", {"row": i, "seed": b})
                                    for b in range(2) for i in range(3)]
        arts = art[art["uid"].notna()]
        assert list(arts["index"].astype(int)) == list(ent["row"])

    def test_batch_location_is_file_colon_row(self, tmp_path):
        cfg = batch_dataset(tmp_path)
        cfg["source"]["batch"]["params"]["location"] = (
            r"^batch_(?P<batch>\d+)/sim\.h5:(?P<row>\d+)$")
        ent, _ = run(tmp_path, cfg)
        assert list(zip(ent["batch"], ent["row"])) == [(b, i) for b in range(2)
                                                       for i in range(3)]

    def test_several_batch_files_need_the_file_part_too(self, tmp_path):
        """Every file's rows start again at 0. With nothing else per row and nothing that
        differs per file, the row number alone gives two files' rows the same parameters;
        capturing part of the file path as well tells them apart. The location description
        says so."""
        cfg = batch_dataset(tmp_path)
        for b in range(2):
            with h5py.File(tmp_path / "sim" / f"batch_{b}" / "sim.h5", "a") as f:
                del f["params"]
        cfg["source"]["batch"]["params"] = {"location": r":(?P<shot>\d+)$"}
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        lines = str(exc.value).splitlines()
        assert lines[0] == ("BATCH_TEST: 6 entities share 3 uids; every entity must be "
                            "distinct.")
        assert lines[1].endswith(": batch_0/sim.h5:0, batch_1/sim.h5:0")
        assert '    equal: {"shot": 0}' in lines
        cfg["source"]["batch"]["params"]["location"] = (
            r"batch_(?P<part>\d+)/sim\.h5:(?P<shot>\d+)$")
        ent, _ = run(tmp_path, cfg, name="ds2")
        assert list(ent.columns) == ["uid", "part", "shot"]
        assert list(ent["uid"]) == [params_uid("BATCH_TEST", {"part": b, "shot": i})
                                    for b in range(2) for i in range(3)]

    def test_an_entity_whose_location_does_not_match_is_named(self, tmp_path):
        cfg = bci_dataset(tmp_path)
        (tmp_path / "bci" / "2012").mkdir()
        with h5py.File(tmp_path / "bci" / "2012" / "BCI_2012_spring.h5", "w") as f:
            f.create_dataset("hgt", data=50.0)
            f.create_dataset("tmp", data=np.zeros((1, 1, 4)))
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        assert str(exc.value).startswith(
            f"{tmp_path / 'bci' / '2012' / 'BCI_2012_spring.h5'}: its location "
            "'2012/BCI_2012_spring.h5' does not match params.location "
            "'BCI_(?P<year>\\\\d{4})(?P<month>[A-Z]{3})\\\\.h5$'")

    def test_a_batch_row_that_does_not_match_is_named(self, tmp_path):
        cfg = batch_dataset(tmp_path)
        cfg["source"]["batch"]["params"]["location"] = r"batch_1/sim\.h5:(?P<row>\d+)$"
        with pytest.raises(ValueError, match=r"batch_0/sim\.h5 row 0: its location "
                                             r"'batch_0/sim\.h5:0' does not match"):
            run(tmp_path, cfg)

    @pytest.mark.parametrize("name, inside", [
        ("temperature", "temperature"),           # a scalar dataset
        ("temperature_units", "temperature_units"),  # a field's attribute label
    ])
    def test_a_name_also_read_in_the_file_is_an_error(self, tmp_path, name, inside):
        cfg = files_dataset(tmp_path)
        cfg["source"]["files"]["params"] = {"location": rf"run_(?P<{name}>\d+)\.h5$"}
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        assert str(exc.value) == (
            f"{tmp_path / 'runs' / 'run_0.h5'}: params.location names {name!r}, and "
            f"{inside!r} is also read inside the file; rename the group in 'location', or "
            f"leave the other out with 'exclude'")

    def test_a_name_starting_with_an_underscore_is_refused(self, tmp_path):
        """'_provenance' was hashed into the uid and then silently dropped from
        entities.parquet (review of #20); a leading '_' is now a contract error."""
        cfg = bci_dataset(tmp_path)
        cfg["source"]["files"]["params"]["location"] = r"BCI_(?P<_provenance>\d{4})"
        with pytest.raises(ContractError, match=r"params\.location: may not name a group "
                                                r"_provenance: a name that starts with '_'"):
            run(tmp_path, cfg)

    def test_a_name_that_parents_a_dotted_key_is_an_error(self, tmp_path, nexus):
        nexus["source"]["files"]["params"]["location"] = r"Ei(?P<instrument>\d+)\.h5$"
        with pytest.raises(ValueError, match=r"Ei30\.h5: params\.location names "
                                             r"'instrument', and 'instrument\.Ei' is also "
                                             r"read inside the file"):
            run(tmp_path, nexus)

    def test_a_name_also_read_in_the_entity_group_is_an_error(self, tmp_path):
        cfg = groups_dataset(tmp_path)
        cfg["source"]["groups"]["params"]["location"] = r"sample_(?P<tenDq>\d+)$"
        with pytest.raises(ValueError, match=r"samples\.h5:/samples/sample_0: "
                                             r"params\.location names 'tenDq', and 'tenDq' "
                                             r"is also read inside the entity group"):
            run(tmp_path, cfg)

    @pytest.mark.parametrize("text, value", [
        ("2011", 2011), ("0042", 42), ("-7", -7), ("+3", 3), ("000", 0),
        ("0.4", 0.4), ("1e-3", 0.001), ("2.5E+2", 250.0), (".5", 0.5), ("5.", 5.0),
        ("-0.25", -0.25), ("007.50", 7.5),
        ("APR", "APR"), ("x0.4", "x0.4"), ("12a", "12a"), ("1_000", "1_000"),
        ("inf", "inf"), ("nan", "nan"), ("0x1F", "0x1F"), ("1e", "1e"), ("", ""),
        ("1.2.3", "1.2.3"), (" 12", " 12"), ("20230501", 20230501),
    ])
    def test_a_value_is_typed_by_its_text(self, tmp_path, text, value):
        d = tmp_path / "typed"
        d.mkdir()
        with h5py.File(d / f"v={text}.h5", "w") as f:
            f.create_dataset("spectrum", data=np.zeros(2))
        cfg = {"label": "Typed", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "v=*.h5",
                                    "params": {"location": r"^v=(?P<v>.*)\.h5$"}}},
               "artifacts": [{"type": "spectrum", "dataset": "/spectrum"}]}
        ent, _ = run(tmp_path, cfg)
        found = ent.loc[0, "v"]
        assert type(found.item() if hasattr(found, "item") else found) is type(value)
        assert found == value

    def test_a_location_parameter_resolves_a_params_collision(self, tmp_path):
        cfg = files_dataset(tmp_path, n=3)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f["temperature"][...] = 300.0
                f["run"][...] = 0
        with pytest.raises(ValueError, match="3 entities share 1 uids"):
            run(tmp_path, cfg)
        cfg["source"]["files"]["params"] = {"location": r"run_(?P<file_run>\d+)\.h5$"}
        ent, _ = run(tmp_path, cfg, name="ds2")
        assert list(ent["file_run"]) == [0, 1, 2] and ent["uid"].nunique() == 3
        assert ent.loc[0, "uid"] == params_uid("FILES_TEST", {
            "file_run": 0, "run": 0, "temperature": 300.0})

    def test_location_parameters_are_in_the_collision_report(self, tmp_path):
        cfg = bci_dataset(tmp_path)
        cfg["source"]["files"]["params"]["location"] = r"BCI_(?P<year>\d{4})"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        lines = str(exc.value).splitlines()
        assert lines[0] == "BCI: 2 entities share 1 uids; every entity must be distinct."
        assert lines[1].endswith(": 2011/BCI_2011APR.h5, 2011/BCI_2011MAY.h5")
        assert lines[2:] == [
            "    no parameter differs",
            '    equal: {"year": 2011, "hgt": 50.0}',
            "Fix: add a field that distinguishes them (a run number, a seed) to the "
            "parameters, from inside the container or from its path with "
            "'params.location', or set 'identity: provenance' under the source.",
        ]


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

    @pytest.mark.parametrize("group", ["/", "/meta"])
    def test_an_attribute_parameter(self, tmp_path, group):
        # params.exclude skips attributes too (#5), so the fix line offers it (#18)
        cfg = files_dataset(tmp_path, attrs=True)
        cfg["source"]["files"]["params"]["group"] = group
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                g = f.require_group(group)
                g.attrs["run"] = i
                g.attrs["path_spectrum"] = "calib_A"
        path = f"{group.rstrip('/')}/path_spectrum"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert "run_0.h5: parameter 'path_spectrum' is named like a locator" in msg
        assert (f"Fix: add '{path}' to params.exclude under the source, or rename the "
                f"attribute 'path_spectrum' in the file.") in msg
        cfg["source"]["files"]["params"]["exclude"] = [path]
        ent, _ = run(tmp_path, cfg, name="ds2")
        assert "path_spectrum" not in ent.columns and len(ent) == 3

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

    @pytest.mark.parametrize("case", ["files", "attrs", "batch", "groups", "params.groups"])
    def test_a_params_location_name(self, tmp_path, nexus, case):
        """A named group of params.location is renamed in the YAML: neither exclude nor
        renaming something in the file can help, whatever else params says."""
        if case in ("files", "attrs"):
            cfg = files_dataset(tmp_path, attrs=case == "attrs")
            cfg["source"]["files"].setdefault("params", {})["location"] = (
                r"run_(?P<path_spectrum>\d+)\.h5$")
            where, name = "runs/run_0.h5", "path_spectrum"
        elif case == "batch":
            cfg = batch_dataset(tmp_path)
            cfg["source"]["batch"]["params"]["location"] = r":(?P<index_spectrum>\d+)$"
            where, name = "sim/batch_0/sim.h5:0", "index_spectrum"
        elif case == "groups":
            cfg = groups_dataset(tmp_path)
            cfg["source"]["groups"]["params"]["location"] = r"_(?P<dataset_spectrum>\d+)$"
            where, name = "grouped/samples.h5:/samples/sample_0", "dataset_spectrum"
        else:
            cfg = nexus
            cfg["source"]["files"]["params"]["location"] = r"Ei(?P<path_E>\d+)\.h5$"
            where, name = "nexus/Ei30.h5", "path_E"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert msg.startswith(f"{tmp_path / where}: parameter '{name}' is named like a "
                              f"locator")
        assert msg.splitlines()[-1] == (f"Fix: rename the named group '{name}' in "
                                        f"params.location.")

    def test_other_names_with_a_locator_prefix_are_parameters(self, tmp_path):
        cfg = files_dataset(tmp_path)  # artifact 'spectrum', shared axis 'energy'
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f["path_length"] = 1.5 + i
                f["path_energy"] = "a shared axis has no locator on the entity"
                f["index_spectrum_2"] = i
        ent, _ = run(tmp_path, cfg)
        assert {"path_length", "path_energy", "index_spectrum_2"} <= set(ent.columns)

    # -- the columns entities.parquet already has (#41) -----------------------

    @pytest.mark.parametrize("name", ["uid", "source_group"])
    def test_a_files_parameter_named_like_a_manifest_column_is_refused(self, tmp_path, name):
        """#41: a scalar called 'uid' beside the parameters became the entity's identity,
        and one called 'source_group' replaced the group each entity was read from, with
        no message at all. Both are refused, naming the file, the parameter and the fix."""
        cfg = files_dataset(tmp_path)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f[name] = 100.0 + i
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert msg.startswith(f"{tmp_path / 'runs' / 'run_0.h5'}: parameter '{name}' is "
                              f"named like a manifest column")
        assert f"'{name}' is a column entities.parquet already has" in msg
        assert (f"Fix: add '/{name}' to params.exclude under the source, or rename it in "
                f"the file. To keep the value, read its group under a name of your own "
                f"with params.groups ({{meta: /}} nests it as 'meta.{name}')") in msg
        cfg["source"]["files"]["params"] = {"exclude": [f"/{name}"]}
        ent, _ = run(tmp_path, cfg, name="ds2")
        assert len(ent) == 3 and list(ent.columns) == ["uid", "run", "temperature",
                                                       "temperature_units"]
        assert all(re.fullmatch(r"[0-9a-f]{16}", u) for u in ent["uid"])

    @pytest.mark.parametrize("name", ["uid", "source_group"])
    def test_an_attribute_named_like_a_manifest_column_is_refused(self, tmp_path, name):
        """The same guard under 'from: attrs', where the attribute names are the keys."""
        cfg = files_dataset(tmp_path, attrs=True)
        cfg["source"]["files"]["params"]["group"] = "/meta"
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                g = f.require_group("meta")
                g.attrs["run"] = i
                g.attrs[name] = "ZZZ"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert f"run_0.h5: parameter '{name}' is named like a manifest column" in msg
        assert (f"Fix: add '/meta/{name}' to params.exclude under the source, or rename "
                f"the attribute '{name}' in the file.") in msg
        cfg["source"]["files"]["params"]["exclude"] = [f"/meta/{name}"]
        ent, _ = run(tmp_path, cfg, name="ds2")
        assert list(ent.columns) == ["uid", "run"] and list(ent["run"]) == [0, 1, 2]
        assert all(re.fullmatch(r"[0-9a-f]{16}", u) for u in ent["uid"])

    def test_a_batch_parameter_named_like_a_manifest_column_is_refused(self, tmp_path):
        cfg = batch_dataset(tmp_path)
        with h5py.File(tmp_path / "sim" / "batch_0" / "sim.h5", "a") as f:
            f["params/uid"] = np.arange(3, dtype=float)
        with pytest.raises(ValueError, match=r"parameter 'uid' is named like a manifest "
                                             r"column(.|\n)*"
                                             r"add '/params/uid' to params.exclude"):
            run(tmp_path, cfg)

    def test_a_groups_parameter_named_source_group_is_refused(self, tmp_path):
        """Left alone, every entity of the file claims the one value the file carries, so
        the column no longer says which group each entity came from."""
        cfg = groups_dataset(tmp_path)
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            for i in range(3):
                f[f"samples/sample_{i}/params/source_group"] = "ZZZ"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert ("samples.h5:/samples/sample_0: parameter 'source_group' is named like a "
                "manifest column") in msg
        assert "add '/params/source_group' to params.exclude" in msg

    @pytest.mark.parametrize("name", ["uid", "source_group"])
    def test_a_params_groups_name_that_is_a_manifest_column_is_refused(self, tmp_path, name):
        """A nested key counts as its first part: 'uid.tenDq' is written into the identity
        column's own name, and registration nests the metadata the same way."""
        cfg = groups_dataset(tmp_path)
        cfg["source"]["groups"]["params"] = {"groups": {name: "params"}}
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert (f"samples.h5:/samples/sample_0: parameter '{name}.tenDq' is named like a "
                f"manifest column") in msg
        assert msg.splitlines()[-1] == f"Fix: rename '{name}' under params.groups."

    def test_a_params_groups_name_of_your_own_still_nests_such_a_field(self, tmp_path):
        """The guard reaches the key's first part only, so the documented fix works: read
        the group under a name of your own and the field keeps its value beside the
        identity, which stays the manifest's own. (A guard: it passes without the fix.)"""
        cfg = groups_dataset(tmp_path)
        cfg["source"]["groups"]["params"] = {"groups": {"meta": "params"}}
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            for i in range(3):
                f[f"samples/sample_{i}/params/uid"] = 100.0 + i
        ent, _ = run(tmp_path, cfg)
        assert sorted(ent["meta.uid"]) == [100.0, 101.0, 102.0]
        assert all(re.fullmatch(r"[0-9a-f]{16}", u) for u in ent["uid"])
        assert sorted(ent["source_group"]) == [f"samples/sample_{i}" for i in range(3)]

    def test_a_label_that_spells_a_manifest_column_is_refused(self, tmp_path):
        """A label is '<field>_<attr>', so a parameter 'source' carrying an attribute
        'group' spells 'source_group' without either name being one."""
        cfg = files_dataset(tmp_path)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f.create_dataset("source", data=f"beam_{i}").attrs["group"] = "ZZZ"
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert ("label 'source_group' (attribute 'group' of parameter 'source') is named "
                "like a manifest column") in msg
        assert ("add '/source' to params.exclude under the source (this also leaves out "
                "the parameter 'source'), or rename the attribute 'group' in the file.") in msg

    @pytest.mark.parametrize("name", ["uid", "source_group"])
    def test_a_table_column_named_like_a_manifest_column_is_refused(self, tmp_path, name):
        """A table's columns are its parameters, so the same two names are its own too;
        no locator name is reserved for it, since it declares no artifacts."""
        d = tmp_path / "specimens"
        d.mkdir()
        pd.DataFrame({"specimen": ["s1", "s2"], name: ["ZZZ", "ZZZ"]}).to_csv(
            d / "meta.csv", index=False)
        cfg = {"label": "Specimens", "metadata": dict(META),
               "source": {"table": {"directory": str(d), "path": "meta.csv",
                                    "id": "specimen"}}}
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert msg.startswith(f"{d / 'meta.csv'}: '{name}' is a reserved column name")
        assert "Fix: rename the column in the table, or drop it" in msg

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


# ---------------------------------------------------------------------------
# a group of arrays: one artifacts entry, one artifact per member (#12, ADR-0012)
# ---------------------------------------------------------------------------

def frames_dataset(tmp_path, files=2, frames=4):
    """Each file: a run number, and /frames holding frame_0000 ... (written out of name
    order), a scalar 'exposure' and a subgroup."""
    d = tmp_path / "movies"
    d.mkdir()
    for i in range(files):
        with h5py.File(d / f"movie_{i}.h5", "w") as f:
            f["run"] = i
            g = f.create_group("frames")
            for k in reversed(range(frames)):
                g.create_dataset(f"frame_{k:04d}", data=np.full((2, 3), 10 * i + k,
                                                                dtype="int16"))
                g[f"frame_{k:04d}"].attrs["units"] = "counts"
            g["exposure"] = 0.5
            g.create_group("thumbs")["frame_0000"] = np.zeros(1)
    return {"label": "Frames Test", "metadata": dict(META),
            "source": {"files": {"directory": str(d), "pattern": "*.h5"}},
            "artifacts": [{"type": "{name}", "group": "/frames"}]}


def rows_of(art, uid):
    rows = art[art["uid"] == uid]
    return list(zip(rows["type"], rows["dataset"], rows["shape"]))


class TestArtifactGroups:

    def test_one_artifact_per_dataset_in_the_group_in_name_order(self, tmp_path):
        ent, art = run(tmp_path, frames_dataset(tmp_path))
        assert len(ent) == 2 and len(art) == 10
        first = ent.loc[ent["run"] == 0, "uid"].item()
        # the scalar is a member; the subgroup and its dataset are not
        assert rows_of(art, first) == [("exposure", "/frames/exposure", "[]")] + [
            (f"frame_{k:04d}", f"/frames/frame_{k:04d}", "[2, 3]") for k in range(4)]
        # the rows are plain manifest rows: no trace of the entry that gave them
        assert list(art.columns) == ["uid", "type", "file", "dataset", "index", "file_size",
                                     "file_mtime", "shape", "dtype", "units"]
        frame = art[(art["uid"] == first) & (art["type"] == "frame_0002")].iloc[0]
        assert frame["dtype"] == "int16" and frame["units"] == "counts"
        assert frame["file"] == "movie_0.h5" and pd.isna(frame["index"])

    def test_members_and_the_type_template(self, tmp_path):
        cfg = frames_dataset(tmp_path)
        cfg["artifacts"] = [
            {"type": "early_{name}", "group": "/frames", "members": "frame_000[0-1]"},
            {"type": "cam_{name}", "group": "frames/", "members": "exp*"},
            {"type": "{{{name}}}", "group": "/frames", "members": "*3"},
            {"type": "run_number", "dataset": "/run"},
        ]
        ent, art = run(tmp_path, cfg)
        assert rows_of(art, ent["uid"].iloc[0]) == [
            ("early_frame_0000", "/frames/frame_0000", "[2, 3]"),
            ("early_frame_0001", "/frames/frame_0001", "[2, 3]"),
            ("cam_exposure", "/frames/exposure", "[]"),
            ("{frame_0003}", "/frames/frame_0003", "[2, 3]"),
            ("run_number", "/run", "[]")]

    def test_members_are_case_sensitive(self, tmp_path):
        cfg = frames_dataset(tmp_path)
        cfg["artifacts"][0]["members"] = "FRAME_*"
        with pytest.raises(ValueError, match="no dataset whose name matches members "
                                             "'FRAME_\\*'"):
            run(tmp_path, cfg)

    def test_the_root_as_the_group(self, tmp_path):
        cfg = frames_dataset(tmp_path, files=1)
        cfg["source"]["files"]["params"] = None
        cfg["artifacts"] = [{"type": "top_{name}", "group": "/"}]
        _, art = run(tmp_path, cfg)
        assert list(zip(art["type"], art["dataset"])) == [("top_run", "/run")]

    def test_a_group_relative_to_each_entity_group(self, tmp_path):
        cfg = groups_dataset(tmp_path)
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            for i in range(3):
                for c in "ba":
                    f[f"samples/sample_{i}/channels/ch_{c}"] = np.arange(4.0) * i
        cfg["artifacts"].append({"type": "trace_{name}", "group": "channels"})
        ent, art = run(tmp_path, cfg)
        uid = ent.loc[ent["source_group"] == "samples/sample_1", "uid"].item()
        assert rows_of(art, uid) == [
            ("spectrum", "/samples/sample_1/spectrum", "[3, 3]"),
            ("trace_ch_a", "/samples/sample_1/channels/ch_a", "[4]"),
            ("trace_ch_b", "/samples/sample_1/channels/ch_b", "[4]")]

    def test_an_absent_group_is_an_error_unless_optional(self, tmp_path, capsys):
        cfg = frames_dataset(tmp_path)
        with h5py.File(tmp_path / "movies" / "movie_1.h5", "a") as f:
            del f["frames"]
        yaml_path = write_yaml(tmp_path / "ds.yml", cfg)
        assert main([str(yaml_path)]) == 1
        err = capsys.readouterr().err
        assert (f"{tmp_path / 'movies' / 'movie_1.h5'}: artifact type='{{name}}' group "
                f"'/frames' not found (mark it 'optional: true' if some entities lack "
                f"it)") in err
        cfg["artifacts"][0]["optional"] = True
        ent, art = run(tmp_path, cfg, name="ds2")
        assert len(ent) == 2 and len(art) == 5
        assert set(art["file"]) == {"movie_0.h5"}

    def test_a_group_under_each_entity_group_a_glob_matches(self, tmp_path):
        # ADR-0011: entity_group may be a glob; the entry is relative to each entity group
        d = tmp_path / "nested"
        d.mkdir()
        with h5py.File(d / "plates.h5", "w") as f:
            for plate in ("plate_a", "plate_b"):
                for well in ("w1", "w2"):
                    g = f.create_group(f"plates/{plate}/{well}")
                    g["params/dose"] = float(len(plate) + int(well[1:]))
                    g["params/tag"] = f"{plate}/{well}"
                    for c in ("red", "blue"):
                        g[f"channels/{c}"] = np.arange(3.0)
        cfg = {"label": "Plates Test", "metadata": dict(META),
               "source": {"groups": {"directory": str(d), "entity_group": "/plates/plate_*",
                                     "params": {"group": "params"}}},
               "artifacts": [{"type": "ch_{name}", "group": "channels"}]}
        ent, art = run(tmp_path, cfg)
        assert sorted(ent["source_group"]) == [
            "plates/plate_a/w1", "plates/plate_a/w2", "plates/plate_b/w1", "plates/plate_b/w2"]
        uid = ent.loc[ent["source_group"] == "plates/plate_b/w2", "uid"].item()
        assert rows_of(art, uid) == [
            ("ch_blue", "/plates/plate_b/w2/channels/blue", "[3]"),
            ("ch_red", "/plates/plate_b/w2/channels/red", "[3]")]
        assert len(art) == 8

    def test_a_group_without_a_matching_member_is_an_error_unless_optional(self, tmp_path):
        cfg = frames_dataset(tmp_path, frames=3)
        cfg["artifacts"] = [{"type": "{name}", "group": "/frames", "members": "shot_*"},
                            {"type": "run", "dataset": "/run"}]
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        assert str(exc.value) == (
            f"{tmp_path / 'movies' / 'movie_0.h5'}: artifact type='{{name}}' group "
            f"'/frames' has no dataset whose name matches members 'shot_*'; it holds 4 "
            f"datasets ('exposure', 'frame_0000', 'frame_0001', ...). Correct 'members' or "
            f"'group', or mark the entry 'optional: true' if some entities lack them")
        cfg["artifacts"][0]["optional"] = True
        _, art = run(tmp_path, cfg, name="ds2")
        assert list(art["type"]) == ["run", "run"]

    def test_a_group_of_subgroups_only_holds_no_dataset(self, tmp_path):
        cfg = frames_dataset(tmp_path)
        cfg["artifacts"] = [{"type": "{name}", "group": "/nested"}]
        with h5py.File(tmp_path / "movies" / "movie_0.h5", "a") as f:
            f.create_group("nested/inner")
        with pytest.raises(ValueError, match=r"group '/nested' has no dataset whose name "
                                             r"matches members '\*'; it holds 0 datasets\. "):
            run(tmp_path, cfg)

    def test_a_dataset_named_as_a_group_is_an_error(self, tmp_path):
        cfg = frames_dataset(tmp_path)
        cfg["artifacts"][0]["group"] = "/run"
        with pytest.raises(KeyError, match="group '/run' is a dataset: name it with "
                                           "'dataset'"):
            run(tmp_path, cfg)
        cfg["artifacts"][0]["optional"] = True
        with pytest.raises(KeyError, match="is a dataset"):
            run(tmp_path, cfg, name="ds2")

    def test_a_dangling_link_is_skipped_with_a_warning(self, tmp_path, capsys):
        cfg = frames_dataset(tmp_path, files=1)
        with h5py.File(tmp_path / "movies" / "movie_0.h5", "a") as f:
            f["frames/frame_9999"] = h5py.SoftLink("/nowhere")
        _, art = run(tmp_path, cfg)
        assert len(art) == 5 and "frame_9999" not in set(art["type"])
        assert "/frames/frame_9999 unreadable" in capsys.readouterr().out

    def test_a_dangling_link_in_the_root_group_is_named_by_its_path(self, tmp_path,
                                                                     capsys):
        cfg = frames_dataset(tmp_path, files=1)
        cfg["source"]["files"]["params"] = None
        cfg["artifacts"] = [{"type": "top_{name}", "group": "/"}]
        with h5py.File(tmp_path / "movies" / "movie_0.h5", "a") as f:
            f["frame_9999"] = h5py.SoftLink("/nowhere")
        _, art = run(tmp_path, cfg)
        assert list(art["type"]) == ["top_run"]
        out = capsys.readouterr().out
        assert f"{tmp_path / 'movies' / 'movie_0.h5'}: /frame_9999 unreadable" in out, out

    def test_a_link_cycle_among_the_members_is_skipped_too(self, tmp_path, capsys):
        """#40: a member HDF5 refuses to resolve raises RuntimeError, not the KeyError a
        dangling link raises. Here as in a params group, it is named and skipped; the
        other members of the group are still registered."""
        cfg = frames_dataset(tmp_path, files=1)
        with h5py.File(tmp_path / "movies" / "movie_0.h5", "a") as f:
            f["frames/frame_8888"] = h5py.SoftLink("/frames/frame_9999")
            f["frames/frame_9999"] = h5py.SoftLink("/frames/frame_8888")
        _, art = run(tmp_path, cfg)
        assert len(art) == 5 and {"frame_8888", "frame_9999"}.isdisjoint(set(art["type"]))
        out = capsys.readouterr().out
        for member in ("frame_8888", "frame_9999"):
            assert f"/frames/{member} unreadable" in out, out

    @pytest.mark.parametrize("second, entry", [
        ({"type": "frame_0001", "dataset": "/frames/frame_0001"},
         "artifacts[1] (dataset '/frames/frame_0001')"),
        ({"type": "{name}", "group": "/frames", "members": "frame_0001"},
         "artifacts[1] (type '{name}', group '/frames', member 'frame_0001')"),
    ])
    def test_a_type_that_comes_twice_names_both_entries(self, tmp_path, second, entry):
        cfg = frames_dataset(tmp_path)
        cfg["artifacts"].append(second)
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        assert str(exc.value) == (
            f"{tmp_path / 'movies' / 'movie_0.h5'}: artifacts[0] (type '{{name}}', group "
            f"'/frames', member 'frame_0001') and {entry} both give the type 'frame_0001'; "
            f"types must be unique within an entity, since each becomes a node key. Change "
            f"a 'type', or narrow 'members'")

    def test_a_type_that_a_shared_axis_has_is_named(self, tmp_path):
        cfg = frames_dataset(tmp_path)
        cfg["shared"] = [{"type": "exposure", "dataset": "/frames/exposure"}]
        with pytest.raises(ValueError, match=re.escape(
                "shared[0] (dataset '/frames/exposure') and artifacts[0] (type '{name}', "
                "group '/frames', member 'exposure') both give the type 'exposure'")):
            run(tmp_path, cfg)
        cfg["artifacts"][0]["members"] = "frame_*"
        _, art = run(tmp_path, cfg, name="ds2")
        assert len(art[art["uid"].notna()]) == 8
        assert list(art.loc[art["uid"].isna(), "type"]) == ["exposure"]

    def test_an_expanded_type_reserves_its_locator_names(self, tmp_path):
        cfg = frames_dataset(tmp_path)
        with h5py.File(tmp_path / "movies" / "movie_1.h5", "a") as f:
            f["dataset_frame_0003"] = 1.0
        with pytest.raises(ValueError) as exc:
            run(tmp_path, cfg)
        msg = str(exc.value)
        assert msg.startswith(f"{tmp_path / 'movies' / 'movie_1.h5'}: parameter "
                              f"'dataset_frame_0003' is named like a locator: registration "
                              f"writes the locator of artifact 'frame_0003'")
        cfg["artifacts"][0]["members"] = "frame_000[0-2]"
        ent, _ = run(tmp_path, cfg, name="ds2")
        assert "dataset_frame_0003" in ent.columns


# ---------------------------------------------------------------------------
# under files and groups, only scalars are parameters; the rest is skipped quietly (#24)
# ---------------------------------------------------------------------------

NON_SCALARS = {"positions": np.arange(7.0), "matrix": np.zeros((3, 4)),
               "column": np.zeros((3, 1)), "nothing": np.zeros(0)}


class TestNonScalarParameters:

    @staticmethod
    def from_doc():
        return " ".join(ParamsSpec.model_fields["from_"].description.split())

    def test_the_from_description_says_so(self):
        assert ("Under 'files' and 'groups' every other dataset, a (7,) array or a (3, 4) "
                "matrix say, is skipped without a message") in self.from_doc()

    def test_the_from_description_says_what_differs_between_files(self):
        doc = self.from_doc()
        assert ("Every container is read on its own, each file and under 'groups' each "
                "entity group, so two more cases pass without a message: a dataset of size 1 "
                "in some of them and a bigger one in others is a parameter only where one of "
                "the rules above makes it one, and a group that some files or entity groups "
                "lack (one of 'groups', say) gives their entities none of its parameters. "
                "Those entities hold null in the columns they miss.") in doc
        assert "'attrs': the group's HDF5 attributes are the parameters, and a group that " \
               "a file or an entity group lacks is an error naming it." in doc

    def test_files_skips_a_non_scalar_dataset_without_a_message(self, tmp_path, capsys):
        cfg = files_dataset(tmp_path)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                for name, value in NON_SCALARS.items():
                    f[name] = value + i
                    f[name].attrs["units"] = "mm"
                f["gain"] = [1.5 + i]           # size 1: a scalar
                f["flag"] = [[i]]               # size 1 as well
        capsys.readouterr()
        ent, _ = run(tmp_path, cfg)
        # the root's (4, 2) spectrum and (4,) energy were never parameters either
        assert set(ent.columns) == {"uid", "temperature", "temperature_units", "run", "gain",
                                    "flag"}
        assert sorted(ent["gain"]) == [1.5, 2.5, 3.5]
        out = capsys.readouterr().out
        assert not any(name in out for name in NON_SCALARS), out

    def test_a_params_groups_entry_skips_them_too(self, tmp_path, capsys):
        cfg = files_dataset(tmp_path)
        cfg["source"]["files"]["params"] = {"groups": {"sample": "/sample"}}
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f["sample/mass"] = 2.0 + i
                for name, value in NON_SCALARS.items():
                    f[f"sample/{name}"] = value
        capsys.readouterr()
        ent, _ = run(tmp_path, cfg)
        assert set(ent.columns) == {"uid", "sample.mass"}
        assert not any(name in capsys.readouterr().out for name in NON_SCALARS)

    def test_groups_skips_a_non_scalar_dataset_without_a_message(self, tmp_path, capsys):
        cfg = groups_dataset(tmp_path)
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            for i in range(3):
                g = f[f"samples/sample_{i}/params"]
                for name, value in NON_SCALARS.items():
                    g[name] = value
                    g[name].attrs["units"] = "mm"
                g["offset"] = [0.25 * i]
        capsys.readouterr()
        ent, _ = run(tmp_path, cfg)
        assert set(ent.columns) == {"uid", "source_group", "tenDq", "offset"}
        assert not any(name in capsys.readouterr().out for name in NON_SCALARS)

    # the two cases of #24's second comment: the rule is applied file by file

    def test_a_dataset_of_size_1_in_some_files_only_is_their_parameter(self, tmp_path,
                                                                        capsys):
        cfg = files_dataset(tmp_path)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f["offset"] = [2.5] if i == 1 else np.arange(7.0)
                f["offset"].attrs["units"] = "mm"
        capsys.readouterr()
        ent, _ = run(tmp_path, cfg)
        rows = ent.set_index("run")
        assert rows.loc[1, "offset"] == 2.5 and rows.loc[1, "offset_units"] == "mm"
        assert rows.loc[[0, 2], ["offset", "offset_units"]].isna().all(axis=None)
        assert "offset" not in capsys.readouterr().out

    def test_a_params_group_some_files_lack_leaves_their_columns_null(self, tmp_path,
                                                                      capsys):
        cfg = files_dataset(tmp_path)
        cfg["source"]["files"]["params"] = {"groups": {"top": "/", "slit": "/slit"}}
        for i in (0, 2):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f["slit/width"] = 0.25 * (i + 1)
        capsys.readouterr()
        ent, _ = run(tmp_path, cfg)
        rows = ent.set_index("top.run")
        assert rows.loc[0, "slit.width"] == 0.25 and rows.loc[2, "slit.width"] == 0.75
        assert pd.isna(rows.loc[1, "slit.width"])
        assert "slit" not in capsys.readouterr().out

    def test_a_params_group_some_entity_groups_lack_leaves_their_columns_null(
            self, tmp_path, capsys):
        cfg = groups_dataset(tmp_path)
        cfg["source"]["groups"]["params"] = {"groups": {"p": "params", "slit": "slit"}}
        with h5py.File(tmp_path / "grouped" / "samples.h5", "a") as f:
            f["samples/sample_2/slit/width"] = 0.5
        capsys.readouterr()
        ent, _ = run(tmp_path, cfg)
        rows = ent.set_index("p.tenDq")
        assert rows.loc[2.0, "slit.width"] == 0.5
        assert rows.loc[[0.0, 1.0], "slit.width"].isna().all()
        assert "slit" not in capsys.readouterr().out

    def test_under_attrs_a_group_a_file_lacks_is_an_error(self, tmp_path):
        cfg = files_dataset(tmp_path, attrs=True)
        cfg["source"]["files"]["params"] = {"groups": {"top": "/", "slit": "/slit"},
                                            "from": "attrs"}
        for i in (0, 2):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f.create_group("slit").attrs["width"] = 0.25 * (i + 1)
        with pytest.raises(KeyError, match="slit"):
            run(tmp_path, cfg)
        with h5py.File(tmp_path / "runs" / "run_1.h5", "a") as f:
            f.create_group("slit").attrs["width"] = 0.5
        ent, _ = run(tmp_path, cfg, name="ds2")
        assert sorted(ent["slit.width"]) == [0.25, 0.5, 0.75]

    def test_under_attrs_a_missing_group_names_the_container_and_the_path(
            self, tmp_path, capsys):
        """#35: the error names the file and the group path, and how to go on, instead of
        h5py's bare "Unable to synchronously open object (object 'slit' doesn't exist)",
        which says nothing about which of the files lacks it."""
        cfg = files_dataset(tmp_path, attrs=True)
        cfg["source"]["files"]["params"] = {"groups": {"top": "/", "slit": "/slit"},
                                            "from": "attrs"}
        with h5py.File(tmp_path / "runs" / "run_0.h5", "a") as f:
            f.create_group("slit").attrs["width"] = 0.25
        with pytest.raises(KeyError) as raised:
            run(tmp_path, cfg)
        message = str(raised.value)
        assert "run_1.h5:/slit" in message and "params.groups.slit '/slit'" in message
        assert "under 'from: attrs' a group that a container lacks is an error" in message
        assert "Fix: narrow 'pattern'" in message
        assert main([str(tmp_path / "ds.yml")]) == 1
        err = capsys.readouterr().err
        assert "Traceback" not in err
        # A KeyError's str() is the repr of its argument, so the message would come out
        # double-quoted with its own quotes escaped, unlike the ValueError errors beside
        # it. The CLI prints it as it was written.
        assert err.startswith("error: /") and err.rstrip().endswith("null columns")
        assert "params.groups.slit '/slit'" in err and "\\'" not in err


# ---------------------------------------------------------------------------

class TestArrayAttributes:
    """#31: a label and an artifact's node metadata carry what a `from: attrs` parameter
    carries, an array attribute's list included, and say when they carry nothing."""

    @staticmethod
    def dataset_with_attrs(tmp_path, attrs):
        """A one-file `files` dataset whose '/signal' artifact and '/temperature' field
        both carry ``attrs``."""
        d = tmp_path / "runs"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            t = f.create_dataset("temperature", data=300.0)
            s = f.create_dataset("signal", data=np.zeros((4, 2)))
            for name, value in attrs(f).items():
                t.attrs[name] = value
                s.attrs[name] = value
        return {"label": "Attrs Test", "metadata": dict(META),
                "source": {"files": {"directory": str(d), "pattern": "*.h5"}},
                "artifacts": [{"type": "signal", "dataset": "/signal"}]}

    def test_an_array_attribute_is_kept_as_a_list(self, tmp_path):
        cfg = self.dataset_with_attrs(tmp_path, lambda f: {
            "axes": np.array(["energy", "time"], dtype=h5py.string_dtype()),
            "edges": np.array([[0.5, 1.5], [2.5, 3.5]]),
            "masked": np.array([True, False]),
            "live": True,
            "units": "K",
            "DIMENSION_LABELS": np.array(["t", "x"], dtype=h5py.string_dtype()),
        })
        ent, art = run(tmp_path, cfg)
        art_row = art[art["uid"].notna()].iloc[0]
        for row, prefix in ((ent.iloc[0], "temperature_"), (art_row, "")):
            assert list(row[f"{prefix}axes"]) == ["energy", "time"]
            assert [list(e) for e in row[f"{prefix}edges"]] == [[0.5, 1.5], [2.5, 3.5]]
            assert list(row[f"{prefix}masked"]) == [True, False]
            assert row[f"{prefix}live"] is np.True_ or row[f"{prefix}live"] is True
            assert row[f"{prefix}units"] == "K"
            # DIMENSION_LABELS holds the axis names, not HDF5's own bookkeeping
            assert list(row[f"{prefix}DIMENSION_LABELS"]) == ["t", "x"]

    def test_hdf5_bookkeeping_attributes_are_still_left_out(self, tmp_path):
        """HDF5's dimension-scale bookkeeping, and netCDF-4's own two attributes, which
        tie a variable to its dimensions and mean nothing outside the file that holds
        them (ADR-0013). They are read as parameters under 'from: attrs', where every
        attribute is a parameter, and left out of labels and artifact metadata."""
        internal = {"CLASS": "DIMENSION_SCALE", "NAME": "energy",
                    "_Netcdf4Coordinates": np.array([0, 1]), "_Netcdf4Dimid": 3}
        cfg = self.dataset_with_attrs(tmp_path, lambda f: {**internal, "units": "K"})
        ent, art = run(tmp_path, cfg)
        for name in internal:
            assert name not in ent.columns and f"temperature_{name}" not in ent.columns
            assert name not in art.columns
        assert art[art["uid"].notna()].iloc[0]["units"] == "K"

    def test_a_reference_attribute_is_noted_and_left_out(self, tmp_path, capsys):
        cfg = self.dataset_with_attrs(tmp_path, lambda f: {
            "target": f["/signal"].ref if "signal" in f else h5py.Empty("f8"),
            "units": "K"})
        capsys.readouterr()
        ent, art = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert "target" not in ent.columns and "target" not in art.columns
        assert ("note: /signal@target is not carried as array metadata: HDF5 object "
                "references cannot be stored") in out
        assert ("note: /temperature@target is not carried as a label: HDF5 object "
                "references cannot be stored") in out
        assert art[art["uid"].notna()].iloc[0]["units"] == "K"

    def test_a_column_of_more_than_one_kind_is_stored_as_json_text(self, tmp_path, capsys):
        """artifacts.parquet holds every type in one table, so one attribute name can be
        a list for one type and a string for another. Arrow has no type for that column;
        it is stored as JSON text, and the run finishes."""
        d = tmp_path / "runs"
        d.mkdir()
        with h5py.File(d / "run_0.h5", "w") as f:
            f.create_dataset("signal", data=np.zeros(4)).attrs["span"] = np.array([0.5, 1.5])
            f.create_dataset("noise", data=np.zeros(4)).attrs["span"] = "half"
        cfg = {"label": "Mixed Test", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5",
                                    "identity": "provenance", "params": None}},
               "artifacts": [{"type": "signal", "dataset": "/signal"},
                             {"type": "noise", "dataset": "/noise"}]}
        capsys.readouterr()
        _, art = run(tmp_path, cfg)
        out = capsys.readouterr().out
        assert ("note: column 'span' of artifacts.parquet holds values of more than one "
                "kind across rows; stored as JSON text") in out
        assert sorted(art.set_index("type")["span"]) == ['"half"', "[0.5, 1.5]"]

    def test_from_attrs_parameters_and_uids_are_untouched(self, tmp_path):
        """The `from: attrs` parameters keep every value they had, and so their uids: only
        labels and artifact metadata changed."""
        cfg = files_dataset(tmp_path, attrs=True)
        for i in range(3):
            with h5py.File(tmp_path / "runs" / f"run_{i}.h5", "a") as f:
                f.attrs["bounds"] = np.array([0.5, 1.5])
        ent, _ = run(tmp_path, cfg)
        row = ent.sort_values("run").iloc[0]
        assert list(row["bounds"]) == [0.5, 1.5] and row["temperature"] == 300.0
        assert row["uid"] == "40ed9463f21966f0"   # what main gave these attributes

    def test_a_parameter_that_changes_type_between_files_no_longer_ends_the_run(
            self, tmp_path, capsys):
        """The same guard: a parameter that is an int in one file and a string in another
        ended the run with pyarrow's own error after the whole walk. The column is stored
        as JSON text instead, with one note, so the author sees which parameter it is."""
        d = tmp_path / "runs"
        d.mkdir()
        for i, gain in enumerate([1, "high"]):
            with h5py.File(d / f"run_{i}.h5", "w") as f:
                f["gain"] = gain
                f["signal"] = np.zeros(4)
        cfg = {"label": "Drift Test", "metadata": dict(META),
               "source": {"files": {"directory": str(d), "pattern": "*.h5"}},
               "artifacts": [{"type": "signal", "dataset": "/signal"}]}
        capsys.readouterr()
        ent, _ = run(tmp_path, cfg)
        assert ("note: column 'gain' of entities.parquet holds values of more than one "
                "kind across rows; stored as JSON text") in capsys.readouterr().out
        assert sorted(ent["gain"]) == ['"high"', "1"]
