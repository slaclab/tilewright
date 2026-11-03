"""The two read paths: the server adapter and ``tilewright.client`` (plus the upload read).

- HDF5 compression filters that h5py does not ship (LZ4, Bitshuffle, ...) must read on
  every path. Each check runs in a fresh interpreter, because anything that imported
  ``hdf5plugin`` earlier in this process would hide a module that forgets to.

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
