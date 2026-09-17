# How to read a registered catalog

Someone has registered a dataset and given you the server's `<URL>` and an `<API_KEY>`.
Getting it to that point is [How to publish a dataset](ONBOARDING.md).

There are two ways to get at an array, and the catalog records enough for both:

| | How | Use when |
|---|---|---|
| [**Through the server**](#read-an-array) | Arrays over HTTP through the Tiled client | Anywhere the server is reachable, and you want a slice rather than the whole file |
| [**Straight from the files**](#read-the-files-directly) | Ask the catalog where the bytes live, then open the HDF5 with h5py | You are on the same filesystem as the data and want bulk reads at full speed |

Start with the server: it needs only the Tiled client (`pip install 'tiled[client]'`),
imports none of this package, and works the same either way a dataset was registered.

## Connect and list

```python
from tiled.client import from_uri
from tiled.queries import Key

c = from_uri("<URL>", api_key="<API_KEY>")

list(c)                                   # dataset keys: ['BROAD_SIGMA', 'LCLS_RIXS_STATIC', ...]
ds = c["BROAD_SIGMA"]                     # a dataset container
dict(ds.metadata)                         # facets: method, material, contact, description, ...
len(ds)                                   # children: the entities + one array per shared axis
```

Dataset containers sit at the root and everything else is beneath one, so always index
the dataset first. Datasets are searchable by their facets too:
`c.search(Key("material") == "NiPS3")`.

## Shared axes

Arrays identical for every entity (an energy grid, a field axis) sit beside the entities
as array children of the dataset, keyed by their `type` and listed in its metadata as
`shared_dataset_<type>`. Iterating children is not iterating entities, so separate them:

```python
shared = {k.removeprefix("shared_dataset_") for k in ds.metadata if k.startswith("shared_dataset_")}
eloss = ds["eloss"][:]                    # (151,), one read, not one per entity
entities = [k for k in ds if k not in shared]
len(entities)                             # the entity count
```

Count entities from that list rather than with `len(ds)`. `len()` is exact when it is the
first thing you ask a container, but the Tiled client (0.2.18) caches the *lower bound*
that a search page reports — 101, its exact-count limit — for a second after the container
has been iterated or its `keys()` listed. A script that walks the keys and then calls
`len(ds)` can read 101 for a dataset of eighteen hundred entities, and the same call a
second later is right again. `len(entities)` is counted from keys you already hold, so it
never lies.

## Search

Search on any parameter the entities carry, and chain as many as you like:

```python
hits = ds.search(Key("sigma") >= 0.04).search(Key("sigma") <= 0.05)
hits = hits.search(Key("gamma") == 0.1)
len(hits)

ent = hits.values().first()
dict(ent.metadata)                        # physics parameters, plus locators
list(ent)                                 # artifact keys under this entity
```

> Only `Key` comparisons (`==`, `>=`, `<=`, ...) are SQL-served. **Never use `Regex`**: it
> is not SQL-backed and silently degrades to filtering every entity client-side.

Nested parameters, the ones a dataset declared with
[`params.groups`](reference/dataset-yaml.md#params), are queried with a dotted key:

```python
hot = ds.search(Key("instrument.Ei") > 50)
nips3 = ds.search(Key("sample.chemical_formula") == "NiPS3")
```

Each entity also carries `path_<type>`, `dataset_<type>`, and (batch only)
`index_<type>`: which file and row it came from. So provenance is searchable
(`Key("path_rixs_spectrum") == "sim_00042.h5"`), and it is what
[reading the files directly](#read-the-files-directly) uses.

## Read an array

Slice an artifact and only those bytes cross the wire:

```python
arr = ent["rixs_spectrum"]
arr.shape                                 # (151, 40)
arr[0:5, :]                               # numpy array
```

The server does the slice, so five rows of a ten-thousand-entity batch file reads five
rows ([sliced reads](explanation/data-model.md#an-entity-is-a-slice)).

Whole entity in one round trip:

```python
import io
buf = io.BytesIO()
ent.export(buf, format="application/x-hdf5")
open("entity.h5", "wb").write(buf.getvalue())
```

## Explore in a notebook

`examples/notebook.py` is a marimo notebook that walks a dataset from its container down
to a plotted array, both read paths side by side. It needs only the server URL, a key,
and a dataset key:

```bash
export TILEWRIGHT_DEMO_DATASET=<KEY>       # and TILED_URL / TILED_API_KEY
uv run --with marimo --with matplotlib marimo run examples/notebook.py    # read it
uv run --with marimo --with matplotlib marimo edit examples/notebook.py   # change it
```

Over SSH, add `--headless` and forward the port it prints.

---

## Read the files directly

HTTP is enough for interactive work, not for a training loop pulling thousands of arrays
where the per-request hop dominates. If you are already on the filesystem that holds the
data, the locator metadata tells you where the bytes are, and `tilewright.client` reads
them:

```python
from tilewright.client import locate, load

locate(ent)          # {'rixs_spectrum': {'file': 'batch_0/sim.h5', 'dataset': '/spectra', 'index': 42}}
load(ent, "rixs_spectrum", base_dir="/mnt/shared/rixs/data/my_dataset")   # the (151, 40) array
load(ent, "rixs_spectrum", base_dir="/mnt/shared/rixs/data/my_dataset",
     slc=(slice(0, 5), 0))                                                 # a (5,) array
```

`base_dir` is the dataset's `directory` as *you* see it; ask whoever onboarded it. The
row index is applied before any slice you pass, which is the one detail that is easy to
get wrong when writing this by hand. Both go to h5py as one index, so a slice reads only
what it selects ([sliced reads](explanation/data-model.md#an-entity-is-a-slice)).

`tilewright.client` imports [`hdf5plugin`](https://pypi.org/project/hdf5plugin/), so
arrays compressed with the filters it ships (LZ4, Bitshuffle, Blosc, Zstd, ...) read like
gzip ones. If you open the files with h5py yourself, `import hdf5plugin` first.

For query-then-bulk-load:

```python
from tilewright.client import query_catalog, load_artifacts

manifest = query_catalog(hits, artifact_type="rixs_spectrum")   # DataFrame: params + locators
arrays = load_artifacts(manifest, artifact_type="rixs_spectrum", base_dir="/mnt/.../my_dataset")
X = np.stack(arrays)
Theta = manifest[["sigma", "gamma"]].to_numpy()
```

None of this works for a dataset registered with `--upload`: the server holds the bytes
and there is no external file to open. Read through the server instead; same array.
