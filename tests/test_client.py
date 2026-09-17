"""The direct-file readers in ``tilewright.client``, offline: entities are stand-ins with
a ``metadata`` mapping, as a Tiled client node has.

A locator is the pair ``path_<type>`` + ``dataset_<type>`` (``index_<type>`` optional);
a lone ``path_*`` key is an ordinary parameter (#18).
"""

from types import SimpleNamespace

import h5py
import numpy as np

from tilewright.client import load, locate, query_catalog


def _entity(**metadata):
    return SimpleNamespace(metadata=metadata)


class _Dataset:
    """A dataset-level client: ``items()`` yields ``(entity key, entity)``."""

    def __init__(self, entities):
        self.entities = entities

    def items(self):
        return iter(self.entities.items())


# PickBlue (zenodo/10277799): SeisBench columns of a table source
TABLE_ROW = _entity(trace_name="ev1", path_p_travel_s=3.5, path_s_travel_s=6.0)


def test_locate_ignores_a_path_key_without_its_dataset_key():
    assert locate(TABLE_ROW) == {}


def test_locate_returns_only_the_pairs():
    ent = _entity(path_length=1.5, temperature=10.0,
                  path_spectrum="f0.h5", dataset_spectrum="/spectrum",
                  path_frames="b.h5", dataset_frames="/frames", index_frames=3)
    assert locate(ent) == {
        "spectrum": {"file": "f0.h5", "dataset": "/spectrum", "index": None},
        "frames": {"file": "b.h5", "dataset": "/frames", "index": 3},
    }


def test_load_reads_an_artifact_of_an_entity_with_a_path_parameter(tmp_path):
    with h5py.File(tmp_path / "f0.h5", "w") as f:
        f["spectrum"] = np.arange(6.0)
    with h5py.File(tmp_path / "b.h5", "w") as f:
        f["frames"] = np.arange(12.0).reshape(4, 3)
    ent = _entity(path_length=1.5,
                  path_spectrum="f0.h5", dataset_spectrum="/spectrum",
                  path_frames="b.h5", dataset_frames="/frames", index_frames=2)
    np.testing.assert_array_equal(load(ent, "spectrum", str(tmp_path)), np.arange(6.0))
    np.testing.assert_array_equal(load(ent, "frames", str(tmp_path)), [6.0, 7.0, 8.0])
    np.testing.assert_array_equal(load(ent, "frames", str(tmp_path), slc=slice(1, None)),
                                  [7.0, 8.0])


def test_query_catalog_skips_a_lone_path_key():
    ds = _Dataset({"T_0": TABLE_ROW, "T_1": _entity(trace_name="ev2", path_p_travel_s=4.0)})
    assert query_catalog(ds, "p_travel_s").empty


def test_query_catalog_keeps_entities_with_the_pair():
    ds = _Dataset({
        "E_0": _entity(path_length=1.5, path_spectrum="f0.h5", dataset_spectrum="/spectrum"),
        "E_1": _entity(path_length=2.5),
        "E_2": _entity(path_spectrum="f2.h5", dataset_spectrum="/spectrum"),
    })
    rows = query_catalog(ds, "spectrum")
    assert list(rows["ent_key"]) == ["E_0", "E_2"]
    assert list(rows["path_spectrum"]) == ["f0.h5", "f2.h5"]
    assert query_catalog(ds, "length").empty
    assert len(query_catalog(ds, "spectrum", limit=1)) == 1
