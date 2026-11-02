"""CLI helpers that do not need a server: dataset-container metadata, manifest lookup,
and the dispatcher."""

import json
import subprocess
import sys

import pytest
from ruamel.yaml import YAML

from tilewright.cli import _build_dataset_metadata, _find_manifests
from tilewright.contract import load_dataset

META = {"method": ["RIXS"], "data_type": "simulation", "material": "NiPS3"}


def test_build_dataset_metadata_keeps_extras_and_adds_shared_locators():
    cfg, _ = load_dataset({
        "label": "X", "metadata": {**META, "prior_distribution": "uniform", "contact": "A <a@b>"},
        "source": {"files": {"directory": "/d"}},
        "artifacts": [{"type": "s", "dataset": "/s"}],
        "shared": [{"type": "energy", "dataset": "/energy"}]})
    md = _build_dataset_metadata(cfg)
    assert md["prior_distribution"] == "uniform" and md["contact"] == "A <a@b>"
    assert md["shared_dataset_energy"] == "/energy"
    assert md["label"] == "X"
    assert "producer" not in md  # None fields are not written


def test_manifest_stamps_come_from_the_schema_metadata(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from tilewright.cli import _manifest_stamps

    fields = {"J1A": {"role": "row_parameter", "dataset": "/params/J1A", "dtype": "float64"}}
    table = pa.table({"uid": ["a"]}).replace_schema_metadata(
        {b"fields": json.dumps(fields).encode(), b"rows": b"42"})
    pq.write_table(table, tmp_path / "entities.parquet")
    assert _manifest_stamps(tmp_path / "entities.parquet") == {"fields": fields, "rows": 42}
    pq.write_table(pa.table({"uid": ["a"]}), tmp_path / "old.parquet")
    assert _manifest_stamps(tmp_path / "old.parquet") == {}   # a manifest from before


def test_find_manifests_uses_the_key_layout(tmp_path):
    ds = tmp_path / ".tilewright" / "datasets"
    ds.mkdir(parents=True)
    yaml_path = ds / "K.yml"
    yaml_path.write_text("label: K\n")
    assert _find_manifests(yaml_path, "K") == (None, None)
    m = tmp_path / ".tilewright" / "manifests" / "K"
    m.mkdir(parents=True)
    (m / "entities.parquet").touch()
    (m / "artifacts.parquet").touch()
    assert _find_manifests(yaml_path, "K") == (m / "entities.parquet", m / "artifacts.parquet")


def test_dispatcher_lists_three_commands():
    out = subprocess.run([sys.executable, "-m", "tilewright.cli", "--help"],
                         capture_output=True, text=True).stdout
    assert [c for c in ("manifest", "register", "delete") if c in out] == ["manifest", "register", "delete"]
    assert "stamp-key" not in out and "generate" not in out


def test_register_refuses_a_yaml_without_key_before_touching_the_network(tmp_path, capsys, monkeypatch):
    from tilewright.cli import register_main

    yaml_path = tmp_path / "ds.yml"
    with open(yaml_path, "w") as f:
        YAML().dump({"label": "No Key", "metadata": META,
                     "source": {"files": {"directory": "/d"}},
                     "artifacts": [{"type": "s", "dataset": "/s"}]}, f)
    monkeypatch.setattr(sys, "argv", ["tilewright register", str(yaml_path),
                                      "--url", "http://127.0.0.1:1", "--api-key", "x"])
    with pytest.raises(SystemExit) as exc:
        register_main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "tilewright manifest" in err and "Cannot reach" not in err
