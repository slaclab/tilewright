"""Unit tests for registration helper functions.

Covers:
- http_register.verify_registration_http: walks the full three-level
  hierarchy (root -> dataset -> entity -> artifact) without crashing.

Run with: uv run --with pytest pytest tests/test_registration_helpers.py -v
"""

from unittest.mock import MagicMock

from tilewright.register import verify_registration_http


# ---------- verify_registration_http: walks the full hierarchy ----------

def _make_artifact(shape=(10, 20), dtype="float32"):
    art = MagicMock()
    art.shape = shape
    art.dtype = dtype
    return art


def _make_entity(art_keys=("array_0",), path_locators=("path_array_0",)):
    ent = MagicMock()
    ent.metadata = {k: f"/data/{k}.h5" for k in path_locators}
    ent.keys.return_value = list(art_keys)
    # The walk only touches index 0, so per-key dispatch isn't exercised;
    # any subscript yields the same artifact mock.
    ent.__getitem__.side_effect = lambda k: _make_artifact()
    return ent


def _make_dataset(ent_keys=("E_0",), with_entity=True):
    ds = MagicMock()
    ds.metadata = {"label": "DS", "material": "GaAs"}
    ds.keys.return_value = list(ent_keys)
    ds.__getitem__.side_effect = lambda k: _make_entity() if with_entity else None
    return ds


def _make_root(ds_keys=("DS",)):
    root = MagicMock()
    root.keys.return_value = list(ds_keys)
    root.__getitem__.side_effect = lambda k: _make_dataset()
    return root


def test_verify_walks_full_hierarchy(capsys):
    """Root -> dataset -> entity -> artifact. All four levels reached."""
    verify_registration_http(_make_root())
    out = capsys.readouterr().out
    assert "Dataset containers at root: 1" in out
    assert "Dataset 'DS'" in out
    assert "entity containers: 1" in out
    assert "Entity 'E_0'" in out
    assert "artifact children: 1" in out
    assert "Artifact 'array_0'" in out
    assert "shape: (10, 20)" in out


def test_verify_skips_shared_axes_when_sampling_entities(capsys):
    """Shared-axis array children (announced in dataset metadata) are not entities."""
    ds = _make_dataset(ent_keys=("energy", "E_0"))
    ds.metadata = {"label": "DS", "shared_dataset_energy": "/energy"}
    root = MagicMock()
    root.keys.return_value = ["DS"]
    root.__getitem__.side_effect = lambda k: ds
    verify_registration_http(root)
    out = capsys.readouterr().out
    assert "shared axes: 1/1 registered as array children ['energy']" in out
    assert "entity containers: 1" in out
    assert "Entity 'E_0'" in out


def test_verify_empty_root(capsys):
    """No datasets registered: clean early return, no crash."""
    root = MagicMock()
    root.keys.return_value = []
    verify_registration_http(root)
    out = capsys.readouterr().out
    assert "No datasets registered yet." in out


def test_verify_entity_with_no_artifacts(capsys):
    """Entity has no array children: warns that server reads will fail."""
    ent = MagicMock()
    ent.metadata = {"path_x": "/data/x.h5"}
    ent.keys.return_value = []
    ds = MagicMock()
    ds.metadata = {}
    ds.keys.return_value = ["E_0"]
    ds.__getitem__.side_effect = lambda k: ent
    root = MagicMock()
    root.keys.return_value = ["DS"]
    root.__getitem__.side_effect = lambda k: ds
    verify_registration_http(root)
    out = capsys.readouterr().out
    assert "WARNING: no array children" in out


def test_verify_entity_without_locators_does_not_warn(capsys):
    """A table-source entity has no path_* locators and no arrays by contract: no
    warning that reads through the server will fail (#8)."""
    ent = MagicMock()
    ent.metadata = {"sample_id": "s1", "temperature_K": 10.5}
    ent.keys.return_value = []
    ds = MagicMock()
    ds.metadata = {"label": "T"}
    ds.keys.return_value = ["T_0"]
    ds.__getitem__.side_effect = lambda k: ent
    root = MagicMock()
    root.keys.return_value = ["T"]
    root.__getitem__.side_effect = lambda k: ds
    verify_registration_http(root, ["T"])
    out = capsys.readouterr().out
    assert "Entity 'T_0'" in out and "(locators: 0)" in out
    assert "WARNING" not in out and "reads through the server will fail" not in out
    assert "no artifacts declared" in out
