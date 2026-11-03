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
| `uid` | **yes** | Entity identity: 16 hex characters, a hash of the parameter values or of the provenance ([identity and keys](../explanation/identity.md)). The Tiled key is `{DATASET_KEY}_{uid[:13]}` |
| `source_group` | `groups` only | The entity's HDF5 group |
| *(any others)* | no | Become the entity container's queryable metadata. A dotted column (`instrument.Ei`) is nested on registration; a `<field>_<attr>` column is that field's attribute label |

Every extra column is carried through verbatim, which is what makes TileWright
dataset-agnostic: no parameter name is known to it.

## `artifacts.parquet`

One row per entity artifact, plus one row per shared axis.

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
| *(any others)* | no | The array's own HDF5 attributes (`units`, `long_name`, ...); become the artifact node's metadata |

## Schema metadata

Both files carry the same keys in their Parquet schema metadata: `generated_at`,
`generator`, `generator_version`, `generator_commit`, `key`, `source`, `identity`,
`fingerprint`, `config_hash`, `entity_count`, `artifact_count`, `shared_count`.
`generator_commit` is the git commit TileWright ran from, suffixed `+dirty` when its
source had uncommitted changes, and empty for an install that is not a checkout. `register` compares `fingerprint` with the YAML's before
it connects, so a manifest generated from a source block the YAML no longer has is refused.

## Snapshot semantics

`shape` and `dtype` are recorded at scan time, so registration never opens an HDF5 file.
The manifest is therefore a snapshot, and registration trusts it.

- A manifest that no longer matches the data is not detected at registration. The read
  adapter re-checks both against the file and raises on a mismatch, so the discrepancy
  surfaces as HTTP 500 on read rather than as silently wrong data. `tilewright manifest`
  rebuilds the snapshot; it is idempotent.
- A manifest with no `shape`/`dtype` columns is rejected at registration.

## Entity metadata written at registration

Registration stamps locator keys onto each entity's metadata, one set per artifact `type`:

| Key | Value |
|---|---|
| `path_<type>` | the manifest's `file`, relative to the source's `directory` |
| `dataset_<type>` | the manifest's `dataset` |
| `index_<type>` | the manifest's `index`; absent for non-batch sources |

They make provenance searchable and are what `tilewright.client.locate` reads
([How to read a registered catalog](../using-the-catalog.md#read-the-files-directly)).
The dataset container is stamped with `storage`, `fingerprint`, `registered_at`, `label`,
the manifest's `generator_version` and `generator_commit` (when it carries them), and one
`shared_dataset_<type>` per shared axis.
