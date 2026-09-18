# Source and entity

**Read this when** you first open the data (Step 2): before you can name an artifact or a
parameter, decide what one entity is and which of the four sources describes the files.

Your data has to match one of four sources. What you call your parameters and your
arrays, and how many entities you have, are up to you.

![Where the entity boundary falls in each source, and where each one keeps its parameters.](diagrams/layouts.svg)

## Inspect across the containers, not one file

Open representative files with `h5py` and list groups, datasets, shapes, dtypes and
attributes. Then compare what you found **across the containers** — every file, and under
`groups` every entity group — not in one: list each container's paths with their shapes
and dtypes and diff the lists. `tilewright manifest` judges every container on its own and
says nothing when they differ, so this is the check that catches it:

- a field of size 1 in some containers and a bigger one in others is a parameter only
  where the [parameter rules](params-and-identity.md#where-parameters-come-from) make it
  one;
- a `params.groups` group that some files or entity groups lack leaves those entities
  without its columns (with `from: attrs`, a missing group is an error naming the
  container);
- an array some entities lack needs `optional: true`, or the manifest stops at the first
  container without it.

Sample when there are thousands of files, and say in the draft which ones you compared.

### Dumping a file that uses hard links

`visit` and `visititems` walk *objects*, and each object is visited once. A field that is
hard-linked into two groups — the usual way a detector's arrays also appear under the
group a reader is pointed at — is therefore listed under one of its paths only, and the
other path looks missing although it resolves perfectly. `visititems_links(print)` walks
*links*, so it prints every path, and so does walking `keys()` group by group:

```python
import h5py
with h5py.File(p) as f:
    f.visititems_links(print)                 # every path, hard links included
    f["/entry/data"].keys()                   # or walk the groups yourself
```

A path this prints is a path the YAML can name, whichever link leads to it.

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

A file that is not HDF5 at all (netCDF-3 classic, a `.gz`, a Parquet sidecar) cannot be
read by the first three; [netCDF and CF](netcdf-cf.md#check-the-file-signature-first)
says how to tell. TileWright reads HDF5 files only, where they lie: a zip or tar archive
is extracted first, and another format is converted, by the owner, before a `files`,
`batch` or `groups` source can name it; or its rows are described with a `table`.

## Choosing between them

Decide from how the entities are packed: one file each → `files`; stacked on axis 0 →
`batch`; one group each → `groups`; not HDF5 at all, with a sidecar table → `table`.

**An array whose path changes from file to file means `groups`.** A `files` artifact names
one absolute path, the same in every file. When a path segment varies per file — openPMD's
file-based encoding writes `/data/<iteration>/fields/rho`, with the iteration number in
every path — make that varying level the entity group: `groups` with
`entity_group: /data` takes each file's iteration group as its entity, and every artifact
and params path is written relative to it (`fields/rho`). Capture the varying name with
`params.location` if it is a value: `':/data/(?P<iteration>\d+)$'`.

**Files that split one acquisition are pieces of one array, not entities.** A writer that
rolls over by size or by process (`scan_000.h5`, `scan_001.h5`, … with identical shapes,
holding consecutive frames of one measurement) makes each file look like an entity, and
`files` registers it that way with every count matching. Nothing in the structure tells
them apart from real entities: look at what the names and the values say (consecutive
frame numbers, one start time), and ask the owner before making each chunk an entity. The
alternatives are the ones for any source whose shape is the problem
([counts and cost](counts-and-cost.md#when-the-sources-shape-is-the-problem)).

**Say what the usual read costs**, in the comment above `source:`, whichever source you
choose: one read, or one per entity, per member, per file.

**When two sources fit at once**, as with one entry per file whose signal also has a short
frame axis, or a stack on axis 0 inside each of several groups, decide on two things:

- **What a reader queries.** The unit they would search for is the entity, and an axis they
  would always want whole stays inside the artifact.
- **What a reader's usual read costs.** Every read goes through one artifact. A
  `(360, ny, nx)` climate cube as a `batch` of 360 entities makes a one-pixel time series
  360 reads, one per entity; as one `files` entity with the time axis inside the artifact,
  it is one slice. When the queries do not settle it, serve the read people will make most.

Say which you chose and why in a comment above `source:`.

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
  reads the `calibration` group of its own site. Name each such group in its own path:
  `recursive: true` and a path that starts with `..` are a contract error in one params
  block.
- **An array beside the entity groups can give one value per entity.** With
  `params: {group: ..}`, a `beam_current` array of 12 values next to `scan_01` …
  `scan_12` gives each scan its own element, in the order of the sorted names. Check that
  the names are zero-padded (`scan_10` sorts before `scan_2`) and that the length matches
  the number of siblings after `exclude_groups`, or the array is skipped without a message.

Two detectors of one site read the same calibration, so under `identity: params` they
would be the same entity; the `location` names keep them apart
([parameters from the location](params-and-identity.md#parameters-from-the-location)).
Which arrays count as one value per entity, the sort order and what is skipped are in
[the `groups` fields](dataset-yaml.md#sourcegroups); entities that read
different parameters get null for the others
([the data model](https://github.com/slaclab/tilewright/blob/main/docs/explanation/data-model.md#entities-with-different-parameters)).
The count is the subgroups of every matching group, less the excluded ones
([expected counts](counts-and-cost.md#expected-counts)).

## What a `table` can and cannot express

A `table` registers rows. Each row is an entity carrying every column as metadata, and
that is all: **no array under a table is served through the catalog**, whoever stores it.
Its identity is its `id` column(s)
([a table's identity](params-and-identity.md#a-tables-identity-is-its-id-columns)).

That matters for the layout where a per-row table sits beside arrays stacked in HDF5, one
row of a pack per entity, with a column that names the pack and the row
(`waveform_ref: pack_02#391`). None of the four sources serves it: `batch` reads the pack
but not the table that indexes it, and `table` reads the table but serves no array. What
you can do — and the choice is the owner's, so put it to them:

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
composite `id` — is in [the `table` fields](dataset-yaml.md#sourcetable).

## Where the source matters later

- **`batch`**: the manifest records each artifact's per-entity shape, leading axis dropped,
  and stores the row number in `index`. An entity is a slice, read by slicing in h5py
  rather than pulling the whole stacked dataset ([sliced reads](https://github.com/slaclab/tilewright/blob/main/docs/explanation/data-model.md#an-entity-is-a-slice)).
- **`groups`**: an artifact's `dataset` path resolves relative to each entity group, and
  so does a params path, which can leave it with `..`.
- **`files`**: the file is the entity boundary, so there is no index.
- **`table`**: entity identity is the `id` column, or several columns listed in `id`
  ([identity and keys](params-and-identity.md#identity-and-keys)); nothing is served as an
  array.

You declare it once and it is never re-inferred: the manifest, the locator metadata, and
the read path all rely on it matching the files. The fields are in
[the `source` section](dataset-yaml.md#source).

## Background

**Why `..` and not a path from the file root:** each site has its own `calibration`, and
one fixed path can name only one of them. **Why a glob and not a number of levels:** a
depth cannot leave out `calibration`, which sits at the same level as the detectors.

**Why the tag owns the keys.** The source is written as one tagged block,
`source: {batch: {...}}`, and each tag accepts only the keys that mean something for it. A
`batch` block has no way to say "parameters are root attributes", because two thousand
entities cannot share one root; a `table` block has no `artifacts`, because there are no
arrays. Combinations that would need a rule to reject them cannot be written. The reader
of one tag reads that tag's keys and nothing else.

**Why only four.** Every extra source is another way of reading files, with its own
failure modes, and another way for two datasets holding the same kind of data to look
different in the catalog. Queries are only worth writing if the catalog is consistent, and
somebody has to pay for that consistency. Here the producer pays once, by arranging the
files to match a source; data that matches none of them does not onboard.

You keep everything else: parameter names, units, artifact names, entity count, what the
arrays mean. None of it is negotiated, and none of it is hardcoded in TileWright.

Four is what the data seen so far needs: simulation sweeps written one run per file, batch
jobs that concatenate their output, collections organized by sample, and run tables for
data that is not HDF5. A fifth would need real data none of these can describe, and a
change to the contract.
