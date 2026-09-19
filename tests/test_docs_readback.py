"""The read-back snippet on the onboarding page runs, at any rank.

`skills/onboarding/reference/walkthrough.md` step 5 is the home of the read-back snippet
(CONTRIBUTING.md, "one fact, one home"), and the onboarding skill sends *every* dataset to it. A corner written
for one shape — `[0:2, 0:2]` — silently returns something else on an artifact of higher
rank: rows out of two different planes, not a corner, and no error to say so. So the
snippet is executed here, as the page ships it, against artifacts of rank 1, 2 and 3.

Offline: `from_uri` is replaced, and the nodes are stand-ins with just the surface the
snippet touches (`metadata`, iteration, `__getitem__`, `shape`, `dtype`, `ndim`).
"""

import re
from pathlib import Path

import numpy as np
import pytest

PAGE = Path(__file__).resolve().parent.parent / "skills" / "onboarding" / "reference" / "walkthrough.md"


def read_back_snippet():
    """The python block under 'Read it back' on the onboarding page."""
    body = PAGE.read_text()
    start = body.index("\n## 5. Read it back\n")
    section = body[start:body.index("\n## ", start + 1)]
    return re.search(r"```python\n(.*?)```", section, re.S).group(1)


class FakeArray:
    """An array client: reports its shape, and records the key it was sliced with."""

    def __init__(self, array):
        self._array = array
        self.shape = array.shape
        self.dtype = array.dtype
        self.ndim = array.ndim
        self.read = []

    def __getitem__(self, key):
        self.read.append(key)
        return self._array[key]


class FakeNode(dict):
    """A container client: children by key, plus metadata."""

    def __init__(self, children, metadata=None):
        super().__init__(children)
        self.metadata = metadata or {}


@pytest.mark.parametrize("shape", [(11,), (11, 5), (24, 4, 4), (6, 3, 3, 3)])
def test_the_snippet_reads_a_corner_of_any_rank(shape, monkeypatch, capsys):
    array = np.arange(int(np.prod(shape)), dtype="f8").reshape(shape)
    spectrum = FakeArray(array)
    axis = FakeArray(np.linspace(0.0, 1.0, 11))
    entity = FakeNode({"spectrum": spectrum}, {"gain": 2, "dwell_us": 250})
    dataset = FakeNode(
        {"ENTITY_0": entity, "energy": axis},
        {"label": "Example", "shared_dataset_energy": "/energy"},
    )
    monkeypatch.setattr(
        "tiled.client.from_uri",
        lambda *a, **k: FakeNode({"MY_DATASET": dataset}),
    )

    exec(read_back_snippet(), {})

    # One read, and it is the corner at the origin: at most 2 along *every* axis.
    (key,) = spectrum.read
    got = array[key]
    assert got.shape == tuple(min(2, n) for n in shape)
    assert np.array_equal(got, array[(slice(0, 2),) * array.ndim])
    assert str(got) in capsys.readouterr().out
