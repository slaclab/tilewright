"""CLI helpers that do not need a server: dataset-container metadata, manifest lookup,
and the dispatcher."""

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


def _run_register(monkeypatch, yaml_path, client):
    import tiled.client

    import tilewright.utils
    from tilewright.cli import register_main

    monkeypatch.setattr(tilewright.utils, "check_server", lambda **kw: True)
    monkeypatch.setattr(tiled.client, "from_uri", lambda *a, **kw: client)
    monkeypatch.setattr(sys, "argv", ["tilewright register", str(yaml_path),
                                      "--url", "http://127.0.0.1:1", "--api-key", "x"])
    register_main()


# ---------------------------------------------------------------------------
# register: the verify step on a table whose columns start with path_ (#8, #18)
# ---------------------------------------------------------------------------

class _Node:
    """An in-memory Tiled container: as much of the client as `register` and its verify
    step use on a dataset without artifacts."""

    def __init__(self, metadata=None):
        self.metadata = dict(metadata or {})
        self.children = {}

    def __contains__(self, key):
        return key in self.children

    def __getitem__(self, key):
        return self.children[key]

    def __len__(self):
        return len(self.children)

    def keys(self):
        return list(self.children)

    def items(self):
        return list(self.children.items())

    def create_container(self, key=None, metadata=None, **kw):
        from tiled.utils import safe_json_dump

        safe_json_dump(metadata)
        self.children[key] = _Node(metadata)
        return self.children[key]


PICKS_YAML = """\
label: Picks table
metadata: {{method: [seismology], data_type: experimental, material: not_applicable}}
source:
  table:
    directory: {directory}
    path: meta.csv
    id: trace_name
"""


def test_register_a_table_with_path_columns_verifies_without_a_warning(tmp_path, monkeypatch,
                                                                        capsys):
    """PickBlue (zenodo/10277799): the SeisBench columns path_p_travel_s and
    path_s_travel_s are table metadata. The verify step must not take them for locators
    and warn that reads through the server will fail (#8)."""
    from tilewright.manifest import generate_manifests

    data = tmp_path / "data"
    data.mkdir()
    (data / "meta.csv").write_text("trace_name,path_p_travel_s,path_s_travel_s,magnitude\n"
                                   "ev1,3.5,6.0,1.2\nev2,4.25,7.5,0.8\n")
    yaml_path = tmp_path / "PICKS_TABLE.yml"
    yaml_path.write_text(PICKS_YAML.format(directory=data))
    generate_manifests(str(yaml_path))
    root = _Node()
    _run_register(monkeypatch, yaml_path, root)
    out = capsys.readouterr().out
    entities = root["PICKS_TABLE"].children
    assert len(entities) == 2
    assert sorted(e.metadata["path_p_travel_s"] for e in entities.values()) == [3.5, 4.25]
    assert "Entity 'PICKS_TABLE_" in out and "no artifacts declared" in out
    assert "WARNING" not in out and "reads through the server will fail" not in out
    assert "Done!" in out
