# Sliced reads

A `batch` dataset keeps ten thousand entities in one HDF5 file, and the catalog serves
each one as if it were a record of its own. Here is how, and what it costs.

## A row is an array, not a number

A batch file is arranged like a table, except each "row" is an array:

```
spectra: shape (10000, 151, 40)
         ─────  ───────────────
         rows   each row is a 151x40 image
```

| Tabular world | Batch HDF5 |
|---|---|
| One CSV with 10K rows | One HDF5 file with 10K spectra |
| Each row is a flat record | Each "row" is a `(151, 40)` array |
| `SELECT * WHERE id = 42` | `file["spectra"][42]` |
| Row filtering in SQL | Slicing on axis 0 |

Slicing on axis 0 is the HDF5 equivalent of a `WHERE` clause.

## An entity is a slice, and the catalog says so

Registration never copies a batch array apart. Each entity is a pointer naming the file,
the dataset inside it, and one row:

```python
parameters = {
    "dataset": "spectra",   # which array in the file
    "slice": "42",          # which row of it
}
```

That lives in the catalog database and is never surfaced. A reader asks for
`client[DATASET][ENTITY][ARTIFACT][0:5]`, gets a `(5, 40)` array, and sees no sign it came
from row 42 of a file holding 9,999 others.

So a batch dataset costs about what its manifest costs: ten thousand entities register
over HTTP, the catalog database lands around 5 MB, and the gigabytes of arrays are never
read. It is the same property that lets a server which cannot see your files be handed
pointers to them anyway.

## Why TileWright ships its own adapter

Tiled's stock HDF5 adapter routes reads through `dask.delayed` → `from_delayed` →
`rechunk`, materializing the whole `(10000, 151, 40)` dataset before applying the user's
slice, so asking for five rows would read all ten thousand spectra.

So arrays are registered against `LazyHDF5ArrayAdapter` (`src/tilewright/adapter.py`)
instead. It reads the `dataset` and `slice` parameters already on the data source and
evaluates `h5py.Dataset[base_index][user_slice]` in one step, never reading more than was
asked for. Cheap slicing is not a bolt-on optimization; it is what makes the data model
possible.

## Why there are two ways in

Serving slices over HTTP is enough for interactive work: a plot, a check, one entity. It
is not enough for a training loop pulling thousands of arrays, where the per-request hop
costs something like an order of magnitude over reading the file directly.

So the catalog records enough for both:

- **Over HTTP.** Works from anywhere, and is the only option for an uploaded dataset where
  no external file exists.
- **Straight from the files.** Every entity carries locator metadata naming its file,
  dataset, and row, so anyone who can already see that filesystem reads with h5py at full
  speed.

Neither path needs the other; both come out of the same registration. Both are shown in
[How to read a registered catalog](../using-the-catalog.md).

## Why the keys are readable

No level of `client[DATASET][ENTITY][ARTIFACT]` uses an opaque UUID. A key like
`EDRIXS_636ce3e41ea05` can be pasted into a message, logged, or held in a script and still
resolve tomorrow, because each level derives from something the producer declared: the
dataset key from the YAML's `label`, the entity key from the hash of its parameters or its
provenance, the artifact key from its `type`. Exact derivations:
[identity and keys](identity.md).

See also [sources](sources.md) for where `batch` sits among the alternatives, and
[the data model](data-model.md) for why the entity carries the parameters.
