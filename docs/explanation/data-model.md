# The data model

A registered dataset has three levels of nested Tiled containers:

<figure class="tw-diagram">
--8<-- "diagrams/hierarchy.svg"
<figcaption>Three levels. Facets on the dataset, physics parameters on the entity, arrays on the artifact, and a shared axis stored once beside the entities.</figcaption>
</figure>

Datasets hold entities; entities hold artifacts. Every parameter on an entity is queryable
metadata, served by SQL, so searches stay fast as a dataset grows.

## The entity is the middle level

An entity is one simulation run, one sample, or one measurement: the parameters you search
on, plus one or more arrays. Two things look like they could do that job instead:

- **A file.** In one dataset a file is a run; in the next, a file holds ten thousand runs.
  See [sources](https://github.com/slaclab/tilewright/blob/main/skills/onboarding/reference/source-and-entity.md).
- **An array.** An entity often has several. A spectrum and a magnetization curve share one
  set of parameters, and you want them back together.

With the entity in the middle, the file layout can change without changing what a query
returns.

The shape follows [ArrayLake](https://docs.earthmover.io/concepts/data-model)'s
Organization → Repo → Group → Array, except ArrayLake's groups are mostly storage
namespaces, whereas here the middle level holds the science.

## Parameters are a free-form dict

Each entity's parameters are stored as a free-form metadata dict, not typed database
columns. Typed columns would perform about as well; the problem is that every dataset
shares one table. Two producers with unrelated physics:

| Producer | Its parameters |
|---|---|
| a spin-wave code | `Ja_meV`, `spin_s`, `g_factor` |
| an atomic-multiplet code | `Udd`, `Delta`, `crystal_10Dq` |

They overlap in nothing. A typed table would have to hold every column any producer ever
needed, each dataset filling in a few and leaving the rest null, and a new producer would
mean a schema migration before its data could be registered at all. Across the fifteen
real datasets on one test server there were 141 distinct parameter names and zero shared
across producers. A free-form dict holds `{Ja_meV, spin_s}` beside
`{Udd, Delta, crystal_10Dq}` with no shared schema and no nulls.

What you give up: nothing checks that two datasets using `sigma` mean the same quantity,
or stops a third from calling it `sig`. The [soft vocabulary](https://github.com/slaclab/tilewright/blob/main/skills/onboarding/reference/metadata-and-vocabulary.md) covers only
the few facets used for cross-dataset discovery, such as `material` and `method`, not the
physics parameters.

## Entities with different parameters

Inside one dataset, entities do not have to read the same parameters: two kinds of entity
group can hold different fields, a group that `params` names can be missing for some
entities, and a group beside the entities can hold more values in one place than in
another. The manifest is still one table, `entities.parquet`, with a column for every
parameter any entity has, so an entity that lacks a parameter has null in that column,
and registration gives its container that key with a null value. Nothing is dropped and
nothing is an error.

One side effect: a column of integers with a null in it is written as floats, so an
entity that has `channels: 8` is registered with `8.0`. Its key does not change, because
the identity is computed from the value as read, before the table is built.

## Dataset metadata is the human record

The dataset container carries the facets (`method`, `material`, `producer`, ...), a
`contact`, and a `description`. The description is the abstract a person reads to decide
whether to open the dataset, and the thing full-text search finds when nobody knows the
key names. Repeating a defining number in it is fine; the rule is that every number in
the prose also exists as a key, and the key is authoritative. Anything a reader should
know before trusting the data (a masked region, a trust ceiling) belongs there too, as
prose plus the keys the author names.

## An entity is a slice

A `batch` dataset keeps ten thousand entities in one HDF5 file, arranged like a table
whose rows are arrays:

```
spectra: shape (10000, 151, 40)
         ─────  ───────────────
         rows   each row is a 151x40 image
```

Slicing on axis 0 is the HDF5 equivalent of a `WHERE` clause, and the catalog takes that
literally. Registration never copies a batch array apart. Each entity's artifact is a
pointer naming the file, the dataset inside it, and one row; a reader asks for
`client[DATASET][ENTITY][ARTIFACT][0:5]`, gets a `(5, 40)` array, and sees no sign it
came from row 42 of a file holding 9,999 others. So a batch dataset costs about what its
manifest costs: ten thousand entities register over HTTP, the catalog database lands
around 5 MB, and the gigabytes of arrays are never read. The same property lets a server
that cannot see your files be handed pointers to them anyway.

Tiled's stock HDF5 adapter would defeat this: it materializes the whole
`(10000, 151, 40)` dataset through dask before applying the user's slice. So arrays are
registered against `LazyHDF5ArrayAdapter` (`src/tilewright/adapter.py`), which hands
h5py the row and the user's slice as one index, `h5py.Dataset[base_index, *user_slice]`,
so HDF5 reads only the chunks that slice touches. Indexing the row first and slicing it
in memory would read the whole row. `tilewright.client.load` reads the same way. Cheap
slicing is not an optimization bolted on afterwards; it is what makes the
entity level possible for batch data. A server has to be told about the adapter
([How to host a server](../host-a-server.md)).

## Two ways in

Serving slices over HTTP is enough for interactive work, not for a training loop pulling
thousands of arrays where the per-request hop dominates. So the catalog records enough
for both: every entity carries locator metadata naming its file, dataset, and row, and
anyone on the same filesystem reads with h5py at full speed. Neither path needs the other;
both come out of the same registration, and an uploaded dataset has only the first.
Both are shown in [How to read a registered catalog](../using-the-catalog.md).

## Readable keys, and the one that is not

No level of `client[DATASET][ENTITY][ARTIFACT]` uses a random UUID: each derives from
something the producer declared, so `EDRIXS_636ce3e41ea05` can be pasted into a message
and still resolve tomorrow ([identity and keys](https://github.com/slaclab/tilewright/blob/main/skills/onboarding/reference/params-and-identity.md#identity-and-keys)). Only two of the three are
*readable*, though. The dataset key is `slug(label)` and the artifact key is its `type`,
both of them words the author chose; the entity key ends in a hash of the entity's
identity ([the shape, and what is hashed](https://github.com/slaclab/tilewright/blob/main/skills/onboarding/reference/params-and-identity.md#the-entity-key-comes-from-the-entitys-identity))
— stable, and saying nothing about the entity.

It shows most under a `groups` source, where the entity already has a name (the HDF5 group
it was read from) that no identity mode puts in the key: `identity: params` hashes the
parameter values and `identity: provenance` hashes the file-and-group path, so
`/panels/panel_north` and `/panels/panel_south` come out as two hashes either way. The name
is not lost. `tilewright manifest` records it in the `source_group` column, and
registration turns that column into queryable metadata like any other, so the group is one
search away:

```python
ent = ds.search(Key("source_group") == "panels/panel_north").values().first()
ent.item["id"]                            # 'TILT_ATLAS_636ce3e41ea05', the entity's key
dict(ent.metadata)["source_group"]        # 'panels/panel_north', the path inside the file
```

Going the other way, key to name, is a lookup of that entity's metadata. The key stays a
hash on purpose: an entity's identity is what it *is*, so a producer who renamed the groups
without changing a value would otherwise re-key every entity. Under `files` and `batch`
the question does not arise the same way, because the file and the row are in metadata
too, as `path_<type>` and `index_<type>`
([search](../using-the-catalog.md#search)).

## What TileWright does

Tiled stores the containers, answers the metadata queries, and slices the arrays.
TileWright decides what shape to register, and writes it the same way every time:
`register.py` builds each entity's metadata from all the manifest's columns, so no
parameter name appears anywhere in its code. That is what makes it dataset-agnostic.

See also [the Parquet manifest](https://github.com/slaclab/tilewright/blob/main/skills/onboarding/reference/manifest.md), where those columns come from,
and [sources](https://github.com/slaclab/tilewright/blob/main/skills/onboarding/reference/source-and-entity.md) for where the entity boundary falls in each kind of data.
