# Sources

Your data has to match one of four sources. What you call your parameters and your
arrays, and how many entities you have, are up to you.

<figure class="tw-diagram">
--8<-- "diagrams/layouts.svg"
<figcaption>Where the entity boundary falls in each source, and where each one keeps its parameters.</figcaption>
</figure>

## What each one looks like

**`files`**: one HDF5 *file* per entity. Each file holds that entity's arrays; its
parameters are scalars or attributes in the file.

```
data/
├── entity_0001.h5   →  /spectrum (600,)  + scalar params tenDq, F2_dd, …
├── entity_0002.h5   →  /spectrum (600,)  + scalars
└── …
```

**`batch`**: many entities stacked along **axis 0** of each file's datasets. Entity *i* is
row *i* of every artifact. Parameters are parallel arrays, one value per entity, usually
in a `/params` group.

```
run.h5
├── /spectra   (10000, 151, 40)   →  entity i = /spectra[i]
└── /params/
    ├── tenDq  (10000,)
    └── F2_dd  (10000,)
```

**`groups`**: one HDF5 *group* per entity inside a file, each group self-contained.

```
samples.h5
└── /samples/
    ├── sample_000/  →  spectrum (151, 40)  +  params/ scalars
    ├── sample_001/  →  spectrum (151, 40)  +  params/ scalars
    └── …
```

**`table`**: the rows of a sidecar table are the entities, and there are no arrays. For
data Tiled cannot read: compressed event files, objects on another system. The catalog
holds each row's metadata and a locator to the real thing.

```
cncs/
├── runs.parquet     →  run_number, Ei, temperature, filename   (one row per entity)
├── run_331525.mcpl.gz
└── …
```

## Why the tag owns the keys

The source is written as one tagged block, `source: {batch: {...}}`, and each tag accepts
only the keys that mean something for it. A `batch` block has no way to say "parameters
are root attributes", because two thousand entities cannot share one root; a `table`
block has no `artifacts`, because there are no arrays. Combinations that would need a
rule to reject them cannot be written. The reader of one tag reads that tag's keys and
nothing else.

## Why only four

Every extra source is another way of reading files, with its own failure modes, and
another way for two datasets holding the same kind of data to look different in the
catalog. Queries are only worth writing if the catalog is consistent, and somebody has to
pay for that consistency. Here the producer pays once, by arranging the files to match a
source; data that matches none of them does not onboard.

You keep everything else: parameter names, units, artifact names, entity count, what the
arrays mean. None of it is negotiated, and none of it is hardcoded in TileWright.

Four is what the data seen so far needs: simulation sweeps written one run per file, batch
jobs that concatenate their output, collections organized by sample, and run tables for
data that is not HDF5. A fifth would need real data none of these can describe, and an
ADR.

## Where the source matters later

- **`batch`**: the manifest records each artifact's per-entity shape, leading axis dropped,
  and stores the row number in `index`. An entity is a slice, read by slicing in h5py
  rather than pulling the whole stacked dataset ([sliced reads](data-model.md#an-entity-is-a-slice)).
- **`groups`**: an artifact's `dataset` path resolves relative to each entity group.
- **`files`**: the file is the entity boundary, so there is no index.
- **`table`**: entity identity is the `id` column, or several columns listed in `id`
  ([identity and keys](identity.md)); nothing is served as an array.

You declare it once and it is never re-inferred: the manifest, the locator metadata, and
the read path all rely on it matching the files.

See also [the `source` section](../reference/dataset-yaml.md#source) for the fields, and
[How to publish a dataset](../ONBOARDING.md) for the steps.
