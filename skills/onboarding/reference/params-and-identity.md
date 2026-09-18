# Parameters and identity

**Read this when** the source is chosen (Step 2): to decide which values become an
entity's queryable parameters, and how every entity keeps a key of its own.

## Where parameters come from

- **Inside the container.** `params.group` names one group whose scalars become flat keys;
  `params.groups` names several, and each nests under the name you give it
  (`{instrument: /entry/instrument}` gives `instrument.Ei`). `from: attrs` reads a group's
  HDF5 attributes instead of its datasets. `exclude` leaves out blobs — an attribute's
  path is `<group path>/<name>`, e.g. `/operator_note` — and `recursive: true` descends
  into subgroups. Field attributes (`units`, ...) are captured automatically as labels
  (`Ei_units`); nothing to declare.
- **What counts as a scalar.** A 0-dim dataset, and a size-1 one (shape `(1,)`, as NeXus
  writes scalars). Any bigger dataset in a params group, a `(7,)` array say, is skipped
  without a message under `files` and `groups`; in `batch`, a 1-D one of length N is one
  value per row. A per-entity log of that shape can still be an
  [artifact](artifacts-and-shared.md), but it is then read and not queried: ask the
  producer for a scalar summary (a mean, a range) if it must be searchable, and when there
  is no producer to ask, say in `description` that it is not searchable.
- **Every container is judged on its own**, without a message: see
  [inspect across the containers](source-and-entity.md#inspect-across-the-containers-not-one-file).
- **In the name only** (a file, directory or group name, or a batch row number):
  `params.location`, below.
- **No per-entity values at all.** `params: null` (valid for `files`, `batch` and
  `groups`) makes identity provenance.
- netCDF-4 dimension placeholders and length-1 coordinate variables look like scalars and
  are not always parameters: [netCDF and CF](netcdf-cf.md#placeholders-and-length-1-coordinates).
- **A name that starts with `_` is not special** in a file. CF's `_FillValue` on a scalar
  field is a label (`x__FillValue`), on an array it is artifact metadata, and under
  `from: attrs` it is a parameter like any other. Only a `params.location` group may not
  start with `_`. Nothing applies a CF attribute
  ([netCDF and CF](netcdf-cf.md#packed-variables)); `exclude` one that only describes the
  encoding, and say in `description` what it means if a reader needs it.

### Names the manifest keeps for itself

A few names belong to the manifest: the locator columns of each artifact `type`, and
`uid` and `source_group` always. Which ones, and the ways out (`exclude`, another name, or
nesting a group under a name of your own), are in
[reserved names](manifest.md#reserved-names); `manifest` refuses a clash and prints the
fix. Every other name is free — `index`, `size` and `type` are ordinary parameters — so do not
rename a producer's field out of caution.

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
  it is part of the identity (below). A batch file whose rows hold nothing else can use
  the row number, `':(?P<shot>\d+)$'`, so that each row keeps a number to query and a key
  of its own, instead of `params: null`. The row number starts again in every file, so
  with several files capture part of the file name too
  ([the `params` fields](dataset-yaml.md#params)).
- **Every entity must match, and a name comes from one place.** Try the expression with
  `re.search` on every name you listed: `tilewright manifest` stops at an entity whose
  location does not match, and at a name that is also read inside the file or group
  ([troubleshooting](troubleshooting.md#tilewright-manifest-the-data)).

## Identity and keys

Three things in the catalog have to be stable and unambiguous: a dataset's key, an
entity's key, and which data a dataset container describes. Each is derived, not chosen.

### The dataset key comes from the label

You write `label: Okafor NiPS3 Powder`; `tilewright manifest` writes
`key: OKAFOR_NIPS3_POWDER` into the YAML. The rule is uppercase with runs of anything
else collapsed to one underscore. A key that no longer matches its label is an error,
never a silent rewrite, because the old key may already hold registered data.

Two people who pick the same label get the same key. What keeps that from merging their
data is the fingerprint.

### The fingerprint says which data a container holds

`tilewright manifest` hashes the facts that identify *which data* a YAML describes: the
source tag, the directory as the server sees it, the file pattern or table path, the
params spec, the identity mode, and a table's `id` when it is a list. Not the label, not
the metadata. The params spec's `location` counts only when it is set, so a YAML written
before `location` existed keeps its fingerprint; adding or changing a `location` gives a
new one. Of the `artifacts`, only an entry that names a `group` counts, by its `group` and
`members`: like `pattern`, they are a rule that picks which parts of the files the
dataset is. A `/` at either end of `group` is dropped first, as the manifest drops it, so
`frames` and `/frames` count as one group. The rule is hashed, not the members it found,
because `register` checks the fingerprint without opening a file. An entry that names a
`dataset` does not count, so a YAML without a group entry keeps its fingerprint. The hash
goes into the manifest, and `tilewright register` stamps it on the dataset container as
`fingerprint`.

When the key already exists on the server:

| The container's fingerprint | What `register` does |
|---|---|
| matches | proceeds; existing entities are skipped, new ones added. With `--update`, the YAML's metadata is merge-patched in first, and Tiled keeps the previous version as a revision |
| differs | refuses, prints both fingerprints and the container's label and description, and asks for a different label |
| absent (registered before fingerprints) | refuses unless `--adopt`, which stamps it |

Copying the same files to a new directory and re-registering under the old label is the
"differs" case. A rename is cheap; silently merging two copies would not be.

### The entity key comes from the entity's identity

An entity key is `<DATASET_KEY>_<uid[:13]>`, and the uid is a hash. Of what depends on
the source's `identity`:

**`params`** (the default): a hash of the parameter *values*. The same physics is the same
entity across re-registration and file moves, which is what a simulation sweep wants and
what makes re-running `register` safe. The cost is that two entities with identical
parameters would collide, so `tilewright manifest` refuses that, names the colliding
entities, what differs between them and the parameters they share, and offers the two
fixes: add a distinguishing parameter, or switch identity.

A float is hashed at 12 decimal places, or at 12 significant digits when that keeps more
digits, which is below 0.1. So float noise such as `0.1 + 0.2` is not a new entity, times
of 1e-13 s are as distinct as temperatures of 300 K, and timestamps in seconds a
millisecond apart stay apart. (At 12 decimal places alone, every value below 5e-13 would
hash as 0.0.) From about 1e4 up, 12 decimal places are more digits than a float64 holds,
so there any difference in the stored value is a new entity. Two floats that are equal at
the kept precision are one entity: `2.0` and `2.0000000000001`, or `4e-15` and
`4.0000000000001e-15`. Entities that differ only in such values collide, and the report
lists those values as what differs; the fixes are the same two.

**`provenance`**: a hash of where the entity came from, the file path relative to the
directory plus its row or group. It never collides unless `pattern` or `entity_group`
matches the same thing twice. It is forced when a source declares `params: null`, and it
is the right choice for run-oriented experimental data where repeated measurements share
every setting. Moving the whole directory changes nothing; renaming a file inside it
changes that entity's key.

These two modes belong to the HDF5 sources (`files`, `batch`, `groups`). Nothing about
identity appears in their YAML unless you write `identity: provenance`. **Decide it now:**
repeated measurements (same settings, different runs) are the usual case for a collision;
put a run number in the params, or write `identity: provenance` under the source, and say
which and why in a comment.

**Parameters from the location count too.** A value taken from an entity's path with
`params.location` is a parameter like the ones read inside the file, and `params`
identity hashes it with them. Two files with the same contents whose names carry
different run numbers are two entities. The value follows the name, though: renaming a
file changes it, and with it the entity's key. Moving the whole directory changes
nothing, because the location is relative to `directory`.

### A table's identity is its `id` column(s)

A `table` source has no `identity` key. One column, `id: run_number`, hashes that
column's value; a list, `id: [specimen, replicate]`, hashes the list of values, for a
table where no single column is unique. Check it before drafting:
`df[col].is_unique`. If no single column is, list several, and say in a comment which
rows needed the extra column. Rows that repeat the id values collide like any other
entities: the report shows the columns that tell them apart, and one of those goes into
the list. A table whose rows are equal in every column has no identity to find, and has
to be de-duplicated — that is the owner's decision, so ask.

Where two columns are both unique, prefer the one that **names the measurement** over one
that encodes how the bytes are packed: the key a reader pastes should mean something, and
a repacking must not re-key the dataset.

Why not the row number, which never collides? Because a table gets edited: re-sorting
it gives every entity a new key, and inserting or removing a row re-keys every row after
it, so the next registration would add those entities a second time. The id values stay
with the row wherever it moves.

Changing `id` gives every entity a new key, so after a change, delete the dataset and
register again. The fingerprint tells `register` about some of these changes:

- **A list `id` is part of the fingerprint.** Switching `id: run_number` to
  `id: [run_number, Ei]` changes the fingerprint, and so does a change from a list or
  between lists. `register` then refuses the old key ("already holds different data")
  until you delete the dataset. Without the refusal, the new keys would be added beside
  the old ones.
- **A single column is not part of it.** This keeps the fingerprint of every table
  registered before tables had their own rule; the manifest also still records a table's
  mode as `provenance`. So a change from one single column to another is not refused.

### What a rerun can and cannot see

`register` never opens a file, so it cannot tell whether an array changed. What it can
compare is the modification time and size the manifest recorded against the ones stamped
on the array node when it was registered. A mismatch on a skipped artifact is reported as
changed on disk, the command exits non-zero, and nothing is rewritten: the fix is
regenerate, delete, register. Under `params` identity a regenerated file with the same
parameters would otherwise be skipped silently and the catalog would serve the old bytes;
this check is what stops that.

### What is deliberately not identity

Attribute labels (`Ei_units`) are stored beside a parameter but never hashed, so fixing a
units string does not create a new entity. Dataset-level metadata is not hashed either;
that is what `--update` is for. What the catalog stores is not identity either: a
parameter the transport cannot carry is stored as null and hashed from the manifest all
the same ([values the transport cannot carry](manifest.md#values-the-transport-cannot-carry)).

The exact columns are in [the manifest reference](manifest.md), and the field in
[the `identity` field](dataset-yaml.md#identity).

## Background

**Why a regular expression and not a `{bias_mV:d}` template:** real names need wildcards
for the parts that are not values, and Python already parses the expression. Why not a
table that lists each file's values: it is a second file to keep in step with the data.
