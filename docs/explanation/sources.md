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

## Parameters from the location

Some values live only in a name: a bias voltage in a file called `sweep_250mV.h5`, a cell
number in a directory called `cell07/`, a sample number in a group called `sample_7`, or,
in a batch file, only the row. `params.location` turns them into parameters. It is a
Python regular expression, searched (`re.search`) in the entity's location, and each named
group becomes a parameter:

| Source | Location searched | Example |
|---|---|---|
| `files` | the file path relative to `directory`, with `/` separators | `cell07/sweep_250mV.h5` |
| `groups` | `<file path>:/<group path>` | `samples.h5:/samples/sample_7` |
| `batch` | `<file path>:<row number>` | `shots/part_03.h5:41` |

A `files` location holds the directories below `directory` too, so one expression can
take a value from a directory name and another from the file name:

```yaml
source:
  files:
    directory: /data/cells
    pattern: "cell*/sweep_*.h5"
    params: {location: 'cell(?P<cell>\d+)/sweep_(?P<bias_mV>[+-]?\d+)mV\.h5$'}
```

Every entity then has `cell` (7) and `bias_mV` (250) beside whatever its file holds.
Write the expression in single quotes: YAML keeps every backslash there. In double
quotes `"\d"` is a YAML error, and `"\b"` silently becomes a backspace.

- **The text decides the type.** Digits with an optional sign become an int, so `07`
  is 7 and its zero is gone; a decimal or exponent literal (`0.4`, `1e-3`) becomes a
  float; anything else stays a string. To keep the zeros, capture a letter with the
  digits, `(?P<cell>cell\d+)` gives `"cell07"`. A group has to capture the same kind of
  text for every entity, or the manifest cannot hold the column.
- **Unnamed groups are wildcards.** `'(sweep|ramp)_(?P<bias_mV>[+-]?\d+)mV'` accepts
  either kind of file and keeps only the voltage.
- **A location parameter is a parameter.** It is queryable, and under `identity: params`
  it is part of the identity ([identity and keys](identity.md#the-entity-key-comes-from-the-entitys-identity)).
  A batch file whose rows hold nothing else can use the row number, so that each row
  keeps a number to query and a key of its own. The row number starts again in every
  file; [the `params` fields](../reference/dataset-yaml.md#params) say what to capture
  when the pattern matches several files.
- **Every entity must match, and a name comes from one place.** `tilewright manifest`
  stops at an entity whose location does not match, and at a name that is also read
  inside the file or group ([errors](../reference/errors.md#tilewright-manifest-the-data)).

Why a regular expression and not a `{bias_mV:d}` template: real names need wildcards for
the parts that are not values, and Python already parses the expression. Why not a table
that lists each file's values: it is a second file to keep in step with the data.

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
