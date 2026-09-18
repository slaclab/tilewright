# TileWright and Tiled

TileWright is not a fork of [Tiled](https://blueskyproject.io/tiled/), a wrapper around
it, or an alternative to it. It is a client that registers a particular *shape* into an
otherwise stock Tiled server, plus one array adapter that server loads.

Everything you interact with at read time is Tiled. TileWright is not running.

## What Tiled already does

Tiled is a data access service: the server, the catalog database and its metadata search,
the HTTP API, the chunked array transport, the Python client, authentication, and storage
for arrays written into it. `register.py` adds nothing on top; it calls
`create_container`, `.new()`, and `write_array` with Tiled's own `DataSource`, `Asset`,
and `ArrayStructure` objects.

So no TileWright code executes when you run this:

```python
c = from_uri(URL, api_key=KEY)
c["BROAD_SIGMA"].search(Key("sigma") >= 0.04)
```

That is deliberate, and it is why reading a catalog needs only `pip install 'tiled[client]'`.

## What Tiled deliberately leaves open

Tiled has no opinion about what your data *means*. It will serve any tree you give it.
What it will not do is decide what counts as a record, which is the right call for a
general service.

Point stock Tiled at a directory and it gives you one node per file. Sensible, and not
what a simulation sweep needs:

- 10,000 spectra stacked on axis 0 of one HDF5 dataset are **one** file. Tiled sees one
  array; you want to query one of ten thousand rows inside it.
- The parameters that make an entity findable, `sigma`, `Udd`, `Ja_meV`, are scalars
  *inside* the HDF5. To Tiled they are opaque bytes.
- Two producers describing the same physics with different field names both register
  fine, and neither is findable by a query written against the other.

None of these are Tiled defects. They are the questions Tiled leaves to whoever knows the
data, and TileWright answers them for this kind of data.

## What TileWright adds

- **A fixed shape.** Every dataset registers as the same three nested containers, Dataset
  → Entity → Artifact, so a query written against one dataset means something against the
  next ([the data model](data-model.md)).
- **Entity extraction.** Four sources say where the entity boundary falls
  ([sources](https://github.com/slaclab/TileWright/blob/main/skills/onboarding/reference/sources.md)). Only one resembles the file-per-node default; the others turn
  *part* of a file into an independently queryable record.
- **Parameter harvesting.** The manifest step lifts HDF5 scalars, attributes, and named
  groups into container metadata, where Tiled's SQL-backed search can reach them. This is
  what makes `Key("sigma") >= 0.04` work at all.
- **Stable identity.** Entity keys derive from the physics (or the provenance), dataset
  keys from the label, and a fingerprint keeps two labels from silently merging
  ([identity and keys](https://github.com/slaclab/TileWright/blob/main/skills/onboarding/reference/identity.md)).
- **A soft vocabulary.** Canonical ids for `material`, `method`, `producer` and the other
  facets, so cross-dataset queries stay honest when six groups onboard independently
  ([the soft vocabulary](https://github.com/slaclab/TileWright/blob/main/skills/onboarding/reference/vocabulary.md)).
- **A scan/register split.** `tilewright manifest` records each artifact's shape and dtype
  into [a Parquet manifest](https://github.com/slaclab/TileWright/blob/main/skills/onboarding/reference/manifest.md); `tilewright register` opens no HDF5
  at all. That is what makes 10,000 entities cheap, and what lets a server that cannot
  see your filesystem be handed pointers to it anyway.
- **One server-side adapter.** The only TileWright code that runs inside the server.
  Tiled's stock HDF5 adapter materializes a whole dataset through dask before slicing,
  which is pathological for batch sources; `LazyHDF5ArrayAdapter` slices in h5py instead
  ([sliced reads](data-model.md#an-entity-is-a-slice)). It is dispatched on the private mimetype
  `application/x-hdf5-broker`, which a server must be told about.

## The dividing line

| | Tiled | TileWright |
|---|---|---|
| Serving arrays over HTTP | ✓ | |
| Catalog database, metadata search | ✓ | |
| Client, auth, export formats | ✓ | |
| Storage for uploaded arrays | ✓ | |
| What counts as one record | | ✓ |
| Finding entities inside a file | | ✓ |
| Lifting HDF5 scalars into queryable metadata | | ✓ |
| Identity, keys, fingerprints | | ✓ |
| Cross-dataset vocabulary | | ✓ |
| Registering without opening the files | | ✓ |
| Slicing batch arrays cheaply | | ✓ (adapter) |

In one sentence: **Tiled answers "serve me this array"; TileWright answers "which array?"**

A useful consequence: nothing TileWright registers is TileWright-specific. Delete the
package and the catalog still works, because what is in the server is ordinary Tiled
containers, metadata, and data sources.
