"""The two read paths: the server adapter and ``tilewright.client`` (plus the upload read).

- HDF5 compression filters that h5py does not ship (LZ4, Bitshuffle, ...) must read on
  every path. Each check runs in a fresh interpreter, because anything that imported
  ``hdf5plugin`` earlier in this process would hide a module that forgets to.
- A slice must reach h5py as part of the index, so a small slice of a batch row (or of
  a server block) reads the slice, not the row. The tests count the elements each h5py
  read returns, so a whole-row or whole-block read fails them even when values match.

Run with: uv run --extra test pytest tests/test_read_paths.py -v
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "tilewright"
LZ4, BITSHUFFLE = 32004, 32008


def _fresh_python(code, *argv):
    """Run ``code`` in a new interpreter with no HDF5 plugin directory; return its JSON."""
    env = {k: v for k, v in os.environ.items() if k != "HDF5_PLUGIN_PATH"}
    r = subprocess.run([sys.executable, "-c", code, *map(str, argv)],
                       capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def filters_missing_by_default():
    """A bare h5py here must lack the filters, or these tests prove nothing."""
    got = _fresh_python(
        "import json, sys, h5py\n"
        f"print(json.dumps([h5py.h5z.filter_avail(i) for i in ({LZ4}, {BITSHUFFLE})]"
        " + ['hdf5plugin' in sys.modules]))")
    if any(got):
        pytest.skip(f"this h5py already has LZ4/Bitshuffle without hdf5plugin: {got}")


H5PY_MODULES = sorted(p.stem for p in SRC.glob("*.py")
                      if re.search(r"^import h5py\b", p.read_text(), re.M))


def test_the_module_scan_finds_both_read_paths():
    assert {"adapter", "client", "register"} <= set(H5PY_MODULES), H5PY_MODULES


@pytest.mark.parametrize("module", H5PY_MODULES)
def test_importing_a_module_that_opens_hdf5_registers_the_filters(
        module, filters_missing_by_default):
    got = _fresh_python(
        "import json, importlib, sys, h5py\n"
        f"importlib.import_module('tilewright.{module}')\n"
        f"print(json.dumps([h5py.h5z.filter_avail(i) for i in ({LZ4}, {BITSHUFFLE})]))")
    assert got == [True, True], f"tilewright.{module} leaves LZ4/Bitshuffle unregistered"


READER = r"""
import json, sys
from types import SimpleNamespace
import numpy as np, pandas as pd
from tiled.structures.array import ArrayStructure
from tilewright.adapter import LazyHDF5ArrayAdapter
from tilewright.client import load
from tilewright.register import read_artifact_array

base = sys.argv[1]
want = np.arange(64, dtype=np.uint16).reshape(8, 8)
out = {}
for t in ("gzip", "bslz4", "lz4"):
    ent = SimpleNamespace(metadata={f"path_{t}": "f.h5", f"dataset_{t}": f"/{t}"})
    paths = {
        "adapter.read": lambda: LazyHDF5ArrayAdapter(
            f"{base}/f.h5", f"/{t}", None, ArrayStructure.from_array(want)).read(),
        "client.load": lambda: load(ent, t, base),
        "register.read_artifact_array": lambda: read_artifact_array(
            pd.Series({"file": "f.h5", "dataset": f"/{t}"}), base),
    }
    for name, read in paths.items():
        try:
            out[f"{t} {name}"] = "ok" if np.array_equal(read(), want) else "wrong values"
        except Exception as e:
            out[f"{t} {name}"] = f"{type(e).__name__}: {e}"
print(json.dumps(out))
"""


def test_plugin_filtered_arrays_read_on_every_path(tmp_path, filters_missing_by_default):
    import hdf5plugin

    want = np.arange(64, dtype=np.uint16).reshape(8, 8)
    with h5py.File(tmp_path / "f.h5", "w") as f:
        f.create_dataset("gzip", data=want, chunks=(8, 8), compression="gzip")
        f.create_dataset("bslz4", data=want, chunks=(8, 8),
                         **hdf5plugin.Bitshuffle(nelems=0, cname="lz4"))
        f.create_dataset("lz4", data=want, chunks=(8, 8), **hdf5plugin.LZ4())

    got = _fresh_python(READER, tmp_path)
    failed = {k: v for k, v in got.items() if v != "ok"}
    assert len(got) == 9 and not failed, json.dumps(failed, indent=1)


# ---------- sliced reads ask h5py for the slice, not the row (#7) ----------

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
    from types import SimpleNamespace
    md = {f"path_{t}": file, f"dataset_{t}": f"/{t}"}
    if index is not None:
        md[f"index_{t}"] = index
    return SimpleNamespace(metadata=md)


@pytest.mark.parametrize("ent, slc, want", [
    (_entity("image", "one.h5"), (slice(0, 2), slice(0, 3)), -STACK[0][0:2, 0:3]),
    (_entity("stack", "batch.h5", ROW), (0, slice(0, 5)), STACK[ROW][0, 0:5]),
    (_entity("stack", "batch.h5", ROW), (slice(None, None, -20), -1), STACK[ROW][::-20, -1]),
], ids=["files", "batch", "batch-reversed"])
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
    from tiled.ndslice import NDBlock

    got = _adapter(h5, ROW, BLOCKS).read_block(NDBlock(1, 2))
    assert np.array_equal(got, STACK[ROW][10:20, 20:30])
    assert reads and max(reads) <= 100, f"{reads} (the row is {ROW_SIZE})"


@pytest.mark.parametrize("index", [ROW, None], ids=["batch", "whole-dataset"])
def test_adapter_read_block_applies_the_user_slice_before_reading(h5, reads, index):
    """The server has one block per axis here, so reading the block is reading the row."""
    from tiled.ndslice import NDBlock, NDSlice

    ad = _adapter(h5, index, ONE_BLOCK if index is not None else ((4,),) + ONE_BLOCK)
    got = ad.read_block(NDBlock(0, 0) if index is not None else NDBlock(0, 0, 0),
                        NDSlice(slice(0, 2), slice(0, 3)))
    want = (STACK[ROW] if index is not None else STACK)[0:2, 0:3]
    assert np.array_equal(got, want)
    assert reads and max(reads) <= want.size, reads


SELECTIONS = [
    (slice(0, 2), slice(0, 3)),
    (0, slice(0, 5)),
    -1,
    (slice(None, None, -1), 3),
    (slice(8, 2, -2), slice(-5, None)),
    (slice(None, None, -1), slice(None, None, -7)),
    (Ellipsis, 4),
    (2, Ellipsis),
    Ellipsis,
    (),
    (slice(1, 49, 7), Ellipsis, slice(3, 3)),
    (slice(5, 1),),
    (slice(40, 100),),
    (np.int64(3), np.int64(-2)),
    (-50, -60),
]
FALLBACKS = [[0, 2, 1], (slice(0, 2), [4, 1]), (None, 0), np.arange(50) % 3 == 0]


COMPOSED_BLOCKS = [None, (slice(10, 40), slice(None)), (slice(None, None, -2), slice(5, 55))]


@pytest.mark.parametrize("block", COMPOSED_BLOCKS, ids=["no-block", "block", "reversed-block"])
@pytest.mark.parametrize("sel", SELECTIONS + FALLBACKS, ids=repr)
def test_read_selection_matches_numpy(h5, reads, block, sel):
    """``ds[row][block][sel]``: numpy's values, shape and IndexError, and for a selection
    h5py can take, no read larger than the result."""
    from tilewright.utils import read_selection

    part = STACK[ROW] if block is None else STACK[ROW][block]
    try:
        want = part[sel]
    except IndexError:
        want = None
    with h5py.File(h5 / "batch.h5", "r") as f:
        if want is None:
            with pytest.raises(IndexError):
                read_selection(f["stack"], (ROW,), block, sel)
            return
        got = read_selection(f["stack"], (ROW,), block, sel)
    assert np.shape(got) == np.shape(want)
    assert np.array_equal(got, want)
    if not any(sel is x for x in FALLBACKS):
        assert reads and max(reads) <= np.size(want), reads


@pytest.mark.parametrize("sel", [(50,), (0, -61), (0, 0, 0), (Ellipsis, 0, Ellipsis)], ids=repr)
def test_read_selection_rejects_what_numpy_rejects(h5, sel):
    from tilewright.utils import read_selection

    with pytest.raises(IndexError):
        STACK[ROW][sel]
    with h5py.File(h5 / "batch.h5", "r") as f, pytest.raises(IndexError):
        read_selection(f["stack"], (ROW,), sel)
