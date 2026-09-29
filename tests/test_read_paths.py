"""Sliced reads on both read paths ask h5py for the slice, not the whole row (#7).

The tests count the elements each h5py read returns, so a whole-row read fails them even
when the values match.

Run with: uv run --extra test pytest tests/test_read_paths.py -v
"""

from types import SimpleNamespace

import h5py
import numpy as np
import pytest

STACK = np.arange(4 * 50 * 60, dtype="f8").reshape(4, 50, 60)   # batch: row i = entity i
ROW = 1
ROW_SIZE = STACK[ROW].size                                       # 3,000 elements


@pytest.fixture
def h5(tmp_path):
    with h5py.File(tmp_path / "batch.h5", "w") as f:
        f.create_dataset("stack", data=STACK, chunks=(1, 10, 10))
    with h5py.File(tmp_path / "one.h5", "w") as f:
        f.create_dataset("image", data=-STACK[0], chunks=(10, 10))
    return tmp_path


@pytest.fixture
def reads(monkeypatch):
    """The element count of every h5py read made while the test runs."""
    sizes = []
    real = h5py.Dataset.__getitem__

    def spy(self, args, *a, **k):
        out = real(self, args, *a, **k)
        sizes.append(int(np.size(out)))
        return out

    monkeypatch.setattr(h5py.Dataset, "__getitem__", spy)
    return sizes


def _entity(t, file, index=None):
    md = {f"path_{t}": file, f"dataset_{t}": f"/{t}"}
    if index is not None:
        md[f"index_{t}"] = index
    return SimpleNamespace(metadata=md)


@pytest.mark.parametrize("ent, slc, want", [
    (_entity("image", "one.h5"), (slice(0, 2), slice(0, 3)), -STACK[0][0:2, 0:3]),
    (_entity("stack", "batch.h5", ROW), (0, slice(0, 5)), STACK[ROW][0, 0:5]),
], ids=["files", "batch"])
def test_load_reads_only_the_slice(h5, reads, ent, slc, want):
    from tilewright.client import load

    t = next(iter(ent.metadata))[len("path_"):]
    got = load(ent, t, h5, slc=slc)
    assert np.array_equal(got, want)
    assert reads and max(reads) <= want.size, reads


def _adapter(h5, index, chunks):
    from tiled.structures.array import ArrayStructure, BuiltinDtype
    from tilewright.adapter import LazyHDF5ArrayAdapter

    structure = ArrayStructure(data_type=BuiltinDtype.from_numpy_dtype(STACK.dtype),
                               shape=STACK.shape[1:], chunks=chunks)
    return LazyHDF5ArrayAdapter(str(h5 / "batch.h5"), "/stack", index, structure)


ONE_BLOCK = ((50,), (60,))          # what register's "auto" chunking gives a small array
BLOCKS = ((10,) * 5, (10,) * 6)


def test_adapter_read_reads_only_the_slice_of_a_batch_row(h5, reads):
    from tiled.ndslice import NDSlice

    got = _adapter(h5, ROW, ONE_BLOCK).read(NDSlice(slice(0, 2), slice(0, 3)))
    assert np.array_equal(got, STACK[ROW][0:2, 0:3])
    assert reads and max(reads) <= 6, f"{reads} (the row is {ROW_SIZE})"


def test_adapter_read_block_reads_only_the_block(h5, reads):
    from tiled.ndslice import NDBlock, NDSlice

    got = _adapter(h5, ROW, BLOCKS).read_block(NDBlock(1, 2), NDSlice(slice(0, 2)))
    assert np.array_equal(got, STACK[ROW][10:20, 20:30][0:2])
    assert reads and max(reads) <= 100, f"{reads} (the row is {ROW_SIZE})"


SELECTIONS = [
    (slice(0, 2), slice(0, 3)),
    (0, slice(0, 5)),
    -1,
    (Ellipsis, 4),
    (2, Ellipsis),
    Ellipsis,
    (),
    (slice(1, 49, 7), Ellipsis, slice(3, 3)),
    (slice(40, 100),),
    (np.int64(3), np.int64(-2)),
    (-50, -60),
]
FALLBACKS = [(slice(None, None, -1), 3), (slice(8, 2, -2), slice(-5, None)),
             [0, 2, 1], (slice(0, 2), [4, 1]), (None, 0), np.arange(50) % 3 == 0]


@pytest.mark.parametrize("sel", SELECTIONS + FALLBACKS, ids=repr)
def test_read_slice_matches_numpy(h5, reads, sel):
    """``ds[row][sel]``: numpy's values and shape, and for a selection h5py can take, no
    read larger than the result."""
    from tilewright.utils import read_slice

    want = STACK[ROW][sel]
    with h5py.File(h5 / "batch.h5", "r") as f:
        got = read_slice(f["stack"], ROW, sel)
    assert np.shape(got) == np.shape(want)
    assert np.array_equal(got, want)
    if not any(sel is x for x in FALLBACKS):
        assert reads and max(reads) <= np.size(want), reads
