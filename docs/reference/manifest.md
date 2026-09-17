# The Parquet manifest

`tilewright manifest` writes two Parquet files per dataset; `tilewright register` reads
them and nothing else. They are the contract between the two halves of the pipeline.

```
<data root>/.tilewright/manifests/<KEY>/
├── entities.parquet
└── artifacts.parquet
```

## `entities.parquet`

One row per entity.

| Column | Required | Description |
|---|---|---|
| `uid` | **yes** | Entity identity: 16 hex characters, a hash of the parameter values, of the provenance, or of a table's `id` column(s) ([identity and keys](../explanation/identity.md)). The Tiled key is `{DATASET_KEY}_{uid[:13]}` |
| `source_group` | `groups` only | The entity's HDF5 group |
| *(any others)* | no | Become the entity container's queryable metadata. A dotted column (`instrument.Ei`) is nested on registration; a `<field>_<attr>` column is that field's attribute label, holding a string, a number, a boolean or a list of them (an array attribute as its list) |

Every extra column is carried through verbatim, which is what makes TileWright
dataset-agnostic: no parameter name is known to it.

## `artifacts.parquet`

One row per entity artifact, plus one row per shared axis. A `group` entry in the YAML
gives one row per dataset it matched in that entity, with `{name}` in its `type` filled in
and the dataset's full path in `dataset`; no column records the entry itself.

| Column | Required | Description |
|---|---|---|
| `uid` | conditional | Parent entity id. Null for a shared axis, whose parent is the dataset container |
| `type` | **yes** | The artifact's key under the entity, e.g. `rixs_spectrum` |
| `file` | **yes** | Path to the HDF5 file, relative to the source's `directory` |
| `dataset` | **yes** | HDF5 path to the array inside that file |
| `index` | no | Row on axis 0, for `batch` sources |
| `file_size`, `file_mtime` | no | Size and modification time of the source file when scanned |
| `shape` | **yes** | JSON-encoded shape **as registered**: for `batch`, the leading axis is already dropped |
| `dtype` | **yes** | numpy dtype string, e.g. `float32` |
| *(any others)* | no | The array's own HDF5 attributes (`units`, `long_name`, ...); become the artifact node's metadata. Each holds a string, a number, a boolean or a list of them, so an array attribute (bin edges, `DIMENSION_LABELS`) is its list. HDF5's dimension-scale bookkeeping (`CLASS`, `NAME`, `DIMENSION_LIST`, `REFERENCE_LIST`) and netCDF-4's own two attributes (`_Netcdf4Coordinates`, `_Netcdf4Dimid`), which tie a variable to its dimensions and mean nothing outside the file that holds them, are left out, here and from a label; and so is an attribute that is or holds an HDF5 object or region reference, which points inside one file and which no catalog can follow — that one with a note. Under `params: {from: attrs}` every attribute is a parameter, those names included |

### Columns of more than one kind

One artifact file holds every `type` of the dataset and its shared axes, and every source
file is read on its own. So one column can hold a list in one row and a string in the next
(an attribute that is an array for one artifact type only), or a number in one row and a
string in another (a parameter that changes type between files). Parquet has one type per
column: such a column is written as each value's JSON text (`[0.5, 1.5]`, `"half"`), with
one note naming it, and the run finishes. A query on that key then compares text, so a
parameter that lands there is usually worth fixing in the data
([the note](errors.md#tilewright-manifest-the-data)).

## What an attribute describes

The two tables above say which attribute *values* are carried. Two things about what they
*mean* are nowhere checked, and an author reads them the wrong way round easily:

- **Nothing interprets a value.** A CF `scale_factor` / `add_offset` pair rides along
  beside the stored integers it would scale, unapplied, and a `valid_range` is carried
  without anything ever being compared with it. An attribute is a label the catalog keeps,
  never an instruction it follows.
- **Under a `batch` source the attributes are the stacked dataset's.** One array is split
  into one row per entity, but its attributes are read once, from the array that was split,
  and the same copy lands on every row. So an attribute naming the stack's dimensions
  (`["shot", "row", "col"]` on a stack whose rows are `(4, 3)`) describes the stack, not
  the `shape` in the row beside it, which has already lost the leading axis.

An attribute with no value at all — a null dataspace, which netCDF writers use for an
empty one — is left out of a label and of an artifact's metadata. Under
[`params.from: attrs`](dataset-yaml.md#params) it is a parameter whose value is null.

## Types and nulls

Each column has one type across every row, so the widest value in it wins:

- **Floats are `float64`.** A `float32` dataset is written as `float64`; the uid is
  computed from the value as read, before the table exists.
- **A null widens a column of integers to floats**, the same rule as for an entity that
  lacks a parameter ([the data model](../explanation/data-model.md#entities-with-different-parameters)).
  Two cases are easy to miss. `index` is an integer row number, but a dataset that also
  declares a `shared` axis has rows with no `index`, so the column is `float` (`0.0`,
  `1.0`); registration writes `index_<type>` back as an `int`, and slices land on the row
  it names. And an attribute that only some arrays carry — an `int64` on one artifact type
  and absent on another — becomes a float column, so it reads back as `7.0`.

## Schema metadata

Both files carry the same keys in their Parquet schema metadata: `generated_at`,
`generator`, `key`, `source`, `identity`, `fingerprint`, `config_hash`, `entity_count`,
`artifact_count`, `shared_count`. `register` compares `fingerprint` with the YAML's before
it connects, so a manifest generated from a source block the YAML no longer has is refused.

`config_hash` is the sha256 of the YAML file as it was when the manifest was built. Nothing
compares it: it is a record of which text produced these rows. So editing a comment, or any
line outside `source`, does not oblige a new manifest — the fingerprint is unchanged and
`register` proceeds. What does need one is a change to the data or to the `source` block
(the three procedures are in
[How to publish a dataset](../ONBOARDING.md#4-register-the-dataset)); a changed
`description` or facet is picked up by `register --update` from the YAML, not from here.

## Snapshot semantics

`shape` and `dtype` are recorded at scan time, so registration never opens an HDF5 file.
The manifest is therefore a snapshot, and registration trusts it.

- A manifest that no longer matches the data is not detected at registration. The read
  adapter re-checks both against the file and raises on a mismatch, so the discrepancy
  surfaces as HTTP 500 on read rather than as silently wrong data. `tilewright manifest`
  rebuilds the snapshot; it is idempotent.
- A manifest with no `shape`/`dtype` columns is rejected at registration.
- `file_size` and `file_mtime` describe the file in the `file` column — the one the source
  matched. An array that lives in another file, reached through an external link or as a
  virtual dataset, is not stamped, so the `changed on disk` check
  ([`register`](cli.md#tilewright-register)) never notices a change to it. Where one entity
  spans several files, rebuild the dataset after the linked files change.

## Entity metadata written at registration

Registration stamps locator keys onto each entity's metadata, one set per artifact `type`:

| Key | Value |
|---|---|
| `path_<type>` | the manifest's `file`, relative to the source's `directory` |
| `dataset_<type>` | the manifest's `dataset` |
| `index_<type>` | the manifest's `index`; absent for non-batch sources |

They make provenance searchable and are what `tilewright.client.locate` reads
([How to read a registered catalog](../using-the-catalog.md#read-the-files-directly)).
A `type` with a dot gives locator keys with a dot, such as `path_stage.x`: each is one key
and is never nested, unlike a dotted parameter column.
A locator is the pair `path_<type>` and `dataset_<type>`; `index_<type>` is optional. A
`path_*` key without its `dataset_*` key is an ordinary parameter, such as a table
column `path_length_m`: `locate`, `load`, `query_catalog` and the check at the end of
`tilewright register` pass over it.
The dataset container is stamped with `storage`, `fingerprint`, `registered_at`, `label`,
and one `shared_dataset_<type>` per shared axis.

### Values the transport cannot carry

A float that is not finite — `inf`, `-inf` or NaN — is not a JSON number, and the Tiled
client writes any of them as null whatever is sent. `tilewright register` stores null for
such a value, in dataset metadata, entity parameters, labels and artifact metadata alike,
and prints one note per key, naming where it first met it and how many nodes held it:

```
  note: SPIN_WAVES/SPIN_WAVES_2b1c0f4e8a77d damping_ratio = inf is not a JSON number; stored as null (2 entities)
```

The manifest keeps the value as it was read, so identity is untouched: a uid is hashed
from the manifest, before any transport, and regenerating or re-registering changes
nothing. To keep the information in the catalog, write it as a string (`"inf"`) or leave
the key out of `params`. NaN carries no note: it is also what a manifest row holds where
it has no value for a column, which is not a lost value but an absent one.

### Reserved names

The locators and the parameters share one metadata mapping. So, for every artifact `type`
a dataset declares, `path_<type>`, `dataset_<type>` and `index_<type>` are reserved.
`tilewright manifest` refuses a parameter, an attribute label, a `params.groups` name or
a named group of `params.location` that is one of them (a dotted parameter nests under
its first part, so that part counts), and the message names it
([the fix](errors.md#tilewright-manifest-the-data)).

- A `table` declares no artifacts, so its columns are never refused.
- A shared axis has no locator on the entity, so its `type` reserves nothing.
- A `group` entry reserves the names of each type it expands to, in the entities that
  have that member.
- Other names with these prefixes, such as `path_length`, are ordinary parameters.

Two more names belong to the manifest itself, in every dataset: **`uid` and
`source_group`**, the columns of `entities.parquet` that are not parameters. The contract
refuses them as a named group of `params.location`, and so a name that starts with `_`,
which the manifest keeps for its own bookkeeping. A field of that name read out of a file
takes the column rather than sitting beside it, so rename it in the file or leave it out
with `params.exclude`.

Nothing else is reserved for an entity parameter. A parameter called `index`, `size`,
`type`, `shape`, `dtype`, `file`, `dataset` or `event` is an ordinary column of
`entities.parquet` and reads back under its own name. Those names are reserved one level
down, for an **array's** attributes: an attribute called `uid`, `type`, `file`, `dataset`,
`index`, `shape`, `dtype`, `file_size` or `file_mtime` would overwrite its own row in
`artifacts.parquet`, so it is dropped with one warning
([the message](errors.md#tilewright-manifest-the-data)) and the array is registered
without it.
