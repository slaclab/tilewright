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

## Nested entity groups and values beside them

A `groups` source can take entities deeper than one level, and read the values stored
next to them rather than inside them. Take files where each site holds one group per
detector and a `calibration` group for all of its detectors:

```yaml
source:
  groups:
    directory: /data/detectors
    entity_group: "/*"
    exclude_groups: [calibration]
    params:
      groups: {calibration: ../calibration}
      location: ':/(?P<site>[^/]+)/(?P<detector>[^/]+)$'
```

- **`entity_group` may hold globs.** `"/*"` takes every top-level group, and the entities
  are the subgroups of each one: one per `/<site>/<detector>`.
- **`exclude_groups` names the subgroups that are not entities**, here `calibration`.
- **A params path may start with `..`**, which leaves the entity group: every detector
  reads the `calibration` group of its own site.
- **An array beside the entity groups can give one value per entity.** With
  `params: {group: ..}`, a `beam_current` array of 12 values next to `scan_01` …
  `scan_12` gives each scan its own element, in the order of the sorted names.

Two detectors of one site read the same calibration, so under `identity: params` they
would be the same entity; the `location` names keep them apart
([parameters from the location](#parameters-from-the-location)). Which arrays count as one
value per entity, the sort order and what is skipped are in
[the `groups` fields](../reference/dataset-yaml.md#sourcegroups); entities that read
different parameters get null for the others
([the data model](data-model.md#entities-with-different-parameters)).

Why `..` and not a path from the file root: each site has its own `calibration`, and one
fixed path can name only one of them. Why a glob and not a number of levels: a depth
cannot leave out `calibration`, which sits at the same level as the detectors.

## What a `table` can and cannot express

A `table` registers rows. Each row is an entity carrying every column as metadata, and
that is all: **no array under a table is served through the catalog**, whoever stores it.

That matters for the layout where a per-row table sits beside arrays stacked in HDF5, one
row of a pack per entity, with a column that names the pack and the row
(`waveform_ref: pack_02#391`). None of the four sources serves it: `batch` reads the pack
but not the table that indexes it, and `table` reads the table but serves no array. What
you can do:

- **Register the table and keep the pointer column.** Readers query the metadata, then
  open the pack themselves; name the pack directory in the dataset `metadata` so they know
  where to look.
- **Restack first**, one entity per file (`files`) or one entity per leading-axis row
  (`batch`), and the arrays come with the parameters.

Serving those arrays from the table itself — a locator template per row, as the read paths
already understand `path_`/`dataset_`/`index_` — would need a contract change, and is not
in this one.

### Writing the table yourself

The producer usually ships the table. When there is none, and the data is not HDF5, the
author writes one, and it is an ordinary part of the dataset:

- **What it needs:** one column whose values are unique per entity (or a few columns that
  are unique together, `id: [specimen, replicate]`), whatever a reader must be able to
  query, and a column naming the file or object each row stands for, which `locator` turns
  into a URL.
- **Where it may live:** anywhere under `directory`; `path` names it relative to that
  root. Beside the data is the usual choice, because the YAML lives there too, under
  `.tilewright/`.
- **What it costs:** a file the producer does not maintain. It is data you have derived, so
  say in `description` that you wrote it and from what, and regenerate it when the data
  changes — nothing checks that the table still matches the files.

The rest of a table's rules — every column kept, an empty header cell, a null cell in a
composite `id` — is in [the `table` fields](../reference/dataset-yaml.md#sourcetable).

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

## Many arrays in one group

Some files keep a series as one dataset per step, or one per channel:
`/frames/frame_0000` to `/frames/frame_0099`. One `artifacts` entry names them all:

```yaml
artifacts:
  - {type: "{name}", group: /frames, members: "frame_*"}
```

`tilewright manifest` expands the entry into one artifact per dataset in the group whose
name matches `members`, `frame_0000` to `frame_0099`, and writes each to the manifest as
if it had an entry of its own, so registration and both read paths see nothing new.
`{name}` in `type` is the member's name, so `trace_{name}` over `/channels/ch_a` gives
`trace_ch_a`. A `batch` source does not take this form, because its first artifact sets
the batch size, and neither does `shared`. What counts as a member, and what an absent or
empty group does, is in [the `artifacts` fields](../reference/dataset-yaml.md#artifacts).

Each member is still an array of its own: one more node to register, and one read per
step to get the series back. A few dozen channels are fine. Thousands of per-step
datasets register slowly (that time is spent when you
[register the dataset](../ONBOARDING.md#4-register-the-dataset)) and read slowly: stack
them into one array, a
`(steps, ny, nx)` dataset, or into a `batch` file, before onboarding, and the series
becomes one artifact that slices like any other.

Why expand the entry in the manifest rather than register one stacked array that the
server reads member by member: a stacked array is the better model for a series, but it
needs a new server adapter and new code on both read paths, while the expansion needs
neither.

## Where the source matters later

- **`batch`**: the manifest records each artifact's per-entity shape, leading axis dropped,
  and stores the row number in `index`. An entity is a slice, read by slicing in h5py
  rather than pulling the whole stacked dataset ([sliced reads](data-model.md#an-entity-is-a-slice)).
- **`groups`**: an artifact's `dataset` path resolves relative to each entity group, and
  so does a params path, which can leave it with `..`.
- **`files`**: the file is the entity boundary, so there is no index.
- **`table`**: entity identity is the `id` column, or several columns listed in `id`
  ([identity and keys](identity.md)); nothing is served as an array.

You declare it once and it is never re-inferred: the manifest, the locator metadata, and
the read path all rely on it matching the files.

See also [the `source` section](../reference/dataset-yaml.md#source) for the fields, and
[How to publish a dataset](../ONBOARDING.md) for the steps.
