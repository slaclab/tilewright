# How to publish a dataset

**Read this when** you onboard by hand, or want the whole path in one place. The
`/onboarding` skill follows the same steps and stops for your answers at each decision.

Turn a directory of HDF5 files into a dataset in a Tiled catalog: searchable by its
physics, readable from anywhere.

**Before you start:** [install `tilewright`](https://github.com/slaclab/tilewright/blob/main/docs/install.md),
check the files match one of the [four sources](source-and-entity.md) (TileWright reads
HDF5 only: extract archives and convert other formats first), export `TILED_URL`
and `TILED_API_KEY`, and [pick a transport](paths-and-server.md#pick-a-transport): the
server reads your files, or you upload the arrays.

![What each step reads and writes. Only the last one needs a running server.](diagrams/pipeline.svg)

## 1. Author the dataset YAML

The YAML is the contract: enough about your files to register them without knowing
anything about your science. It lives **with the data**, at
`<data root>/.tilewright/datasets/<KEY>.yml`, so it travels with what it describes.
`tilewright manifest` writes `key` for you, so name the file after the key you expect
(`slug(label)`: `Okafor NiPS3 Powder` becomes `OKAFOR_NIPS3_POWDER`).

### With an agent (recommended)

The package ships an `/onboarding` skill for Claude Code: the directory above this page.
Install it once, then open Claude Code in your data root and type `/onboarding`:

```bash
tilewright skills install
```

Tell it where your data is and what you know about it: the instrument or code that
produced it, the material, who to name as contact, a paper, a README, and whether the
server can see your files. It opens your HDF5 with `h5py` and drafts the YAML from what is
there, then asks you the questions the data cannot answer.

**You are still the reviewer.** An agent reads shapes and dtypes off your files;
`method`, `material`, and `producer` are provenance claims only you can confirm.

### By hand

```bash
mkdir -p .tilewright/datasets
cp <skill>/examples/files.yml .tilewright/datasets/MY_DATASET.yml
```

`<skill>` is this skill's directory: `~/.claude/skills/onboarding` after
`tilewright skills install`, or `skills/onboarding/` in a checkout. Copy the example for
your source (`files`, `batch`, `groups`, `table`, or `files_nexus` for NeXus) and delete
its `key:` line: `manifest` writes the key for your label. Then edit:

- **`label`**: distinctive. On a shared server, include your surname or group:
  `Okafor NiPS3 Powder`, not `My Dataset`. Two people picking the same name land on the
  same key, and the second registration is refused. See the key the label slugs to before
  you commit to it: `tilewright manifest --check` prints it, and an accent, a hyphen or an
  apostrophe in a name comes out as `_`
  ([the rule](dataset-yaml.md#top-level)). If that spelling is not one you want
  pasted around a shared server, write the name plainly in the label and keep it as it is
  really spelled in `contact`, or distinguish the dataset with a group, instrument or
  project token instead of a surname.
- **`metadata`**: [metadata and vocabulary](metadata-and-vocabulary.md). Write the
  description for a person deciding whether to open the dataset, say what a reader should
  know before trusting the data, and give every number in it a key
  ([what counts as a number](dataset-yaml.md#metadata)).
- **`source`**: [source and entity](source-and-entity.md), then
  [parameters and identity](params-and-identity.md); `directory` and `server_base_dir`
  depend on the transport ([paths and the server](paths-and-server.md)).
- **`artifacts`** and **`shared`**: [artifacts and shared axes](artifacts-and-shared.md).
- NeXus or netCDF files: [NeXus](nexus.md), [netCDF and CF](netcdf-cf.md).

Full field list: [the dataset YAML reference](dataset-yaml.md).

## 2. Build the manifests

From the data root:

```bash
tilewright manifest .tilewright/datasets/MY_DATASET.yml
```

It validates the contract (every problem at once, one sentence each), writes `key:` into
the YAML, scans the files, and records each artifact's path, shape and dtype in
[two Parquet manifests](manifest.md) under `.tilewright/manifests/<KEY>/`.
Nothing has touched the network yet. `--check` validates and stops.

**Check the reported entity and artifact counts against your files.** If they are wrong,
fix the YAML and rerun: usually a broad `pattern`, the wrong batch axis, or the wrong
entity group ([expected counts](counts-and-cost.md#expected-counts)).

## 3. Make local and server paths agree

<a id="paths-where-your-view-and-the-servers-view-differ"></a>

Uploading: nothing to do. The server reads your files: `directory`, `server_base_dir` and
the server's `readable_storage` must describe the same bytes, and the server needs
TileWright's adapter — [paths and the server](paths-and-server.md#when-the-server-reads-the-files),
with a complete [server config](config-pointer.yml).

## 4. Register the dataset

Register a sample smaller than the dataset first (`-n 5`, or `-n 1` for a dataset of a
few entities), then the rest. When the server reads your files:

```bash
tilewright register -n 5 .tilewright/datasets/MY_DATASET.yml
tilewright register .tilewright/datasets/MY_DATASET.yml
```

No array bytes move: registration reads the manifest and never opens an HDF5 file,
which is what makes ten thousand entities cheap. When you upload the arrays:

```bash
tilewright register --upload -n 5 .tilewright/datasets/MY_DATASET.yml
tilewright register --upload .tilewright/datasets/MY_DATASET.yml
```

This moves the real data. Parameters become queryable metadata, arrays stream to the
server, shared axes stream once each, and the container is stamped `storage: uploaded`.

Either way registration is incremental: an existing entity is skipped, so the second
command continues from the first and an interrupted run resumes. Its summary counts that
run only, so the sample's entities appear under `Skipped` the second time.

How long a run takes, and what to do when the source's shape makes it slow, is in
[counts and cost](counts-and-cost.md#how-long-registering-takes).

If the key already exists on the server, `register` compares fingerprints. The same data
proceeds; different data under your label is refused, with both fingerprints and the
existing container's description printed, and you pick another label
([identity and keys](params-and-identity.md#identity-and-keys)).

Three kinds of change, three procedures:

| You changed | Do |
|---|---|
| Dataset metadata in the YAML (description, contact, a facet) | `tilewright register --update`. One node is patched; Tiled keeps the previous metadata as a revision |
| Nothing, but more entities exist (an interrupted run, new files) | `tilewright manifest --append`, then `register`. Existing entities are skipped |
| The files, a path, a shape or dtype, a table's `id` | `tilewright manifest`, `tilewright delete MY_DATASET`, `register`. Existing artifacts are never rewritten in place, and a rerun that finds a registered artifact's source file changed on disk stops and prints these three commands |

## 5. Read it back

Registration never opens a pointer-registered array, so a read through the server is the
real check. From any machine that can reach it:

```python
from tiled.client import from_uri

client = from_uri("<URL>", api_key="<KEY>")
ds = client["MY_DATASET"]              # the key manifest wrote

# A dataset's children are its entities *plus* one array per shared axis, so drop
# the axes before taking "the first entity".
shared = {k.removeprefix("shared_dataset_") for k in ds.metadata if k.startswith("shared_dataset_")}
entities = [k for k in ds if k not in shared]
entity = ds[entities[0]]

len(entities)                          # the entity count manifest printed (or -n)
print(dict(ds.metadata))               # the facets you wrote, plus storage/fingerprint/registered_at
print(dict(entity.metadata))           # this entity's physics parameters

spectrum = entity["spectrum"]          # the array client: no bytes have moved yet
print(spectrum.shape, spectrum.dtype)  # the shape and dtype the manifest recorded
corner = (slice(0, 2),) * spectrum.ndim   # at most 2 along *every* axis, at any rank
print(spectrum[corner])                # a corner: the server slices, these bytes cross
[ds[k].shape for k in shared]          # every shared axis
```

Ask the array client for `.shape` and read a **small slice** — built from `.ndim`, so the
corner means the same thing at every rank: 2×2 of a rank-2 artifact, and of a rank-3 one
the 2×2×2 block at the origin, rather than the two rows out of two different planes that a
literal `[0:2, 0:2]` returns without complaining. `spectrum[:]` would pull the whole array
over HTTP, which for a multi-gigabyte artifact is a long wait and proves nothing the slice
does not: both go through the same adapter, the same file and the same pointer. Compare
the slice with the same corner read from the HDF5 by hand if you want the values checked
too: open the file the entity's `path_<type>` names, which is relative to the source's
`directory` (or `server_base_dir`), and read `dataset_<type>` there. A corner can be all
zeros (a detector's edge, a padded border), and zeros match anything; if it is, compare a
slice from the middle of the array instead, built from `.shape` the same way.

Metadata on the dataset, parameters on the entity, an array at the shape you registered:
the whole contract, proven. Collaborators need nothing beyond the Tiled client.

A `table` dataset has no artifact to read, so its proof is the other three: the entity
count, one row's metadata, and a `Key` search that returns the rows you expect
([search](https://github.com/slaclab/tilewright/blob/main/docs/using-the-catalog.md#search)).

Next: [read a registered catalog](https://github.com/slaclab/tilewright/blob/main/docs/using-the-catalog.md).

## 6. Start over

```bash
tilewright delete MY_DATASET
```

This removes the catalog entries and, for an uploaded dataset, the arrays the server
stored, since the catalog is their only home. Your HDF5 files are never touched.

## Troubleshooting

[Troubleshooting](troubleshooting.md) has the common symptoms and every `tilewright
manifest` message; flags and exit codes are in
[the `tilewright` reference](https://github.com/slaclab/tilewright/blob/main/docs/reference/cli.md).
