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


# ---------------------------------------------------------------------------
# register: metadata written in the YAML reaches Tiled as plain JSON types (#2)
# ---------------------------------------------------------------------------

FLOAT_YAML = """\
label: Float Meta
metadata:
  method: [RIXS]
  data_type: experimental
  material: NiPS3
  sample_length_mm: 1.5
  public: &flag true
  measured_on: 2024-05-06T07:08:09Z
  temperatures_K: [5.3, 10, 134.5]
  beam: {{energy_eV: 931.5, polarization: "sigma"}}
source:
  files:
    directory: {directory}
    pattern: "*.h5"
artifacts:
  - {{type: signal, dataset: /signal}}
"""


def _keyed_float_dataset(tmp_path):
    """A files-source YAML with float (and nested) metadata, keyed and manifested."""
    import h5py
    import numpy as np

    from tilewright.manifest import generate_manifests

    data = tmp_path / "data"
    data.mkdir()
    for i in range(2):
        with h5py.File(data / f"e{i}.h5", "w") as f:
            f["run"] = i
            f["signal"] = np.arange(4.0) + i
    yaml_path = tmp_path / "FLOAT_META.yml"
    yaml_path.write_text(FLOAT_YAML.format(directory=data))
    generate_manifests(str(yaml_path))
    return yaml_path


def _serializing_client():
    """A mock Tiled client that serializes metadata the way ``tiled.client`` does."""
    from unittest.mock import MagicMock

    from tiled.utils import safe_json_dump

    sent = []

    def create_container(key=None, metadata=None, **kw):
        safe_json_dump(metadata)  # raises TypeError on what the real client refuses
        sent.append(metadata)
        node = MagicMock()
        node.__contains__.return_value = False
        node.create_container.side_effect = create_container
        return node

    client = MagicMock()
    client.__contains__.return_value = False
    client.create_container.side_effect = create_container
    return client, sent


def _run_register(monkeypatch, yaml_path, client):
    import tiled.client

    import tilewright.utils
    from tilewright.cli import register_main

    monkeypatch.setattr(tilewright.utils, "check_server", lambda **kw: True)
    monkeypatch.setattr(tiled.client, "from_uri", lambda *a, **kw: client)
    monkeypatch.setattr(sys, "argv", ["tilewright register", str(yaml_path),
                                      "--url", "http://127.0.0.1:1", "--api-key", "x"])
    register_main()


def test_register_sends_float_and_nested_yaml_metadata_as_plain_json(tmp_path, monkeypatch, capsys):
    yaml_path = _keyed_float_dataset(tmp_path)
    client, sent = _serializing_client()
    _run_register(monkeypatch, yaml_path, client)
    assert "Done!" in capsys.readouterr().out
    dataset_md = sent[0]
    assert dataset_md["sample_length_mm"] == 1.5 and type(dataset_md["sample_length_mm"]) is float
    assert dataset_md["public"] is True  # an anchored bool is a ruamel int subclass
    assert dataset_md["measured_on"] == "2024-05-06T07:08:09+00:00"
    assert dataset_md["temperatures_K"] == [5.3, 10, 134.5]
    assert [type(v) for v in dataset_md["temperatures_K"]] == [float, int, float]
    assert dataset_md["beam"] == {"energy_eV": 931.5, "polarization": "sigma"}
    assert type(dataset_md["beam"]) is dict and type(dataset_md["beam"]["energy_eV"]) is float
    assert len(sent) == 3  # the dataset container and both entities were created
