# The dataset YAML contract

*Generated from `src/tilewright/contract.py` by `scripts/build_yaml_reference.py`; edit
the models, not this page.*

One YAML describes one dataset. To author one, see [How to publish a dataset](../ONBOARDING.md);
to copy a working file, see `examples/datasets/<source>.yml`, one per source tag with its
expected counts in the header.

## Shape

```yaml
label: Broad Sigma               # authored; the key derives from it
key: BROAD_SIGMA                 # written by `tilewright manifest`
metadata: {...}                  # facets; method, data_type, material required
source:
  <files | batch | groups | table>:   # exactly one tag
    directory: /abs/path
    ...
artifacts: [{type, dataset}, ...]
shared: [{type, dataset}, ...]     # optional
```

Unknown keys are rejected everywhere except inside `metadata`, where any key becomes a
queryable facet. An empty string counts as missing. Every problem is reported at once, one
sentence each, as `contract error: <field> <what to do>`.

## Top level

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `label` | str | **yes** |  | Human-readable dataset name. The catalog key is derived from it. |
| `key` | str | no |  | Catalog key, slug(label); written by 'tilewright manifest'. If present it must equal slug(label). |
| `metadata` | mapping | **yes** |  | Dataset-level facets; method, data_type and material are required. |
| `source` | mapping | **yes** |  | Where the entities come from: one tag. |
| `artifacts` | list | no |  | Arrays each entity exposes; at least one, except for 'table'. |
| `shared` | list | no |  | Arrays shared by every entity, registered once under the dataset. |

## `metadata`

Values of the facets marked *vocabulary facet* are soft-checked: a known alias is rewritten
to its id, an unknown value warns and registers as written
([the soft vocabulary](../explanation/vocabulary.md)).

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `method` | list of str | **yes** |  | Scientific methods, e.g. ['RIXS']; at least one. Vocabulary facet. |
| `data_type` | str | **yes** |  | 'simulation', 'experimental' or 'benchmark'. Vocabulary facet. |
| `material` | str | **yes** |  | Material or system studied, e.g. 'NiPS3'; 'not_applicable' for non-physical data. Vocabulary facet. |
| `producer` | str | no |  | Code that produced or reduced the data ('sunny_jl', 'mantid'). Vocabulary facet. |
| `project` | str | no |  | Project or collaboration ('MAIQMag'). Vocabulary facet. |
| `proposal` | str | no |  | Beamtime proposal id ('IPTS-37598'). Vocabulary facet. |
| `facility` | str | no |  | Where experimental data was collected ('SNS'). Vocabulary facet. |
| `instrument` | str | no |  | Instrument or beamline ('SEQUOIA', 'JEOL NeoARM'). Free text. |
| `contact` | str | no |  | Who to ask about this dataset, as 'Name <email>'. |
| `description` | str | no |  | One paragraph a reader uses to decide whether to open the dataset. Repeat the defining numbers here freely, but every number in it must also exist as a metadata key: the key is authoritative, the prose is the summary. |

## `source`

Exactly one of the four tags. Each owns only the keys below, so an illegal combination
cannot be written ([sources](../explanation/sources.md)).

### `source.files`

One HDF5 file per entity.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | str | **yes** |  | Absolute path of the data root on the machine that runs 'tilewright manifest' (and '--upload'). |
| `server_base_dir` | str | no |  | The same root as the Tiled server sees it, when its mount differs. Ignored for --upload. |
| `identity` | <enum 'Identity | no | `params` | How entity uids are computed; see Identity. Write it only to override. |
| `pattern` | str | no | `**/*.h5` | Glob for the entity files under 'directory'. |
| `params` | mapping or `null` | no |  | Where the parameters live in each file; default: the root. Only scalar datasets are parameters (see 'from'); any other member, a (6,) array say, is skipped without a message. 'null' declares that entities have no parameters (identity becomes provenance). |

### `source.batch`

Many entities stacked along axis 0 of each file's datasets; entity i is row i.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | str | **yes** |  | Absolute path of the data root on the machine that runs 'tilewright manifest' (and '--upload'). |
| `server_base_dir` | str | no |  | The same root as the Tiled server sees it, when its mount differs. Ignored for --upload. |
| `identity` | <enum 'Identity | no | `params` | How entity uids are computed; see Identity. Write it only to override. |
| `pattern` | str | no | `**/*.h5` | Glob for the batch files under 'directory'. |
| `params` | mapping or `null` | no |  | Where the parameters live in each file; default: the root. N is the file's leading axis (that of the first artifact). Only 1-D datasets of length N are per-entity values, one per row; 0-dim datasets are broadcast to every entity in the file; any other member, (N, 1) included, is skipped without a message. 'null' declares that entities have no parameters (identity becomes provenance). |

### `source.groups`

One HDF5 group per entity inside each file.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | str | **yes** |  | Absolute path of the data root on the machine that runs 'tilewright manifest' (and '--upload'). |
| `server_base_dir` | str | no |  | The same root as the Tiled server sees it, when its mount differs. Ignored for --upload. |
| `identity` | <enum 'Identity | no | `params` | How entity uids are computed; see Identity. Write it only to override. |
| `pattern` | str | no | `**/*.h5` | Glob for the files under 'directory'. |
| `entity_group` | str | no |  | Group whose subgroups are the entities ('/samples'). Default: the file's top-level groups. |
| `params` | mapping or `null` | no |  | Where the parameters live, relative to each entity group; default: the entity group itself. Only scalar datasets are parameters (see 'from'); any other member, a (6,) array say, is skipped without a message. 'null' declares none. |

### `source.table`

A sidecar table whose rows are the entities: for data Tiled cannot read.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `directory` | str | **yes** |  | Absolute path of the data root on the machine that runs 'tilewright manifest' (and '--upload'). |
| `server_base_dir` | str | no |  | The same root as the Tiled server sees it, when its mount differs. Ignored for --upload. |
| `identity` | <enum 'Identity | no | `params` | How entity uids are computed; see Identity. Write it only to override. |
| `path` | str | **yes** |  | Parquet or CSV file, relative to 'directory'. Every column becomes entity metadata. |
| `id` | str | **yes** |  | Column whose value identifies a row; it is the entity's identity and must be unique across rows. When no column is, add one to the table (system_id and tilt joined, say). Changing it re-keys every entity: delete the registered dataset, then register again. |
| `locator` | mapping | no |  | Extra metadata rendered per row from '{column}' templates, e.g. {globus_url: 'https://.../{filename}'}. |

### `params`

Where an entity's parameters are read from, within its container (the file for `files`
and `batch`, the entity group for `groups`). Scalars found there become the entity's
queryable metadata; each field's own HDF5 attributes ride along as `<field>_<attr>`
labels, stored beside the value and never part of the identity.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `group` | str | no |  | One HDF5 group whose fields become flat metadata keys. '/' is the container itself. Default '/' when neither 'group' nor 'groups' is given. |
| `groups` | dict[str, str] | None | no |  | Several groups, keyed by the name each nests under: {instrument: /entry/instrument, sample: /entry/sample} -> metadata.instrument.Ei, metadata.sample.mass; queryable as Key('instrument.Ei'). |
| `from` | `datasets` \| `attrs` | no | `datasets` | 'datasets': 0-dim datasets in the group are parameters (in 'batch', a 1-D dataset of length N is one value per entity). 'attrs': the group's HDF5 attributes are the parameters. |
| `recursive` | bool | no | `False` | Descend into subgroups, nesting one level per subgroup. |
| `exclude` | list of str | no |  | HDF5 paths (same frame as the group paths) to skip: a JSON blob, say. |

`groups` nests: `{instrument: /entry/instrument}` puts `Ei` at `metadata.instrument.Ei`,
queryable as `Key("instrument.Ei") > 50`.

### `identity`

How an entity's uid is computed (``source.<tag>.identity``).

    - ``params`` (default) — sha256 of the parameter *values*. The same physics is the same
      entity across re-registration and file moves; two entities with identical
      parameters are a contract error (``tilewright manifest`` names them).
    - ``provenance`` — sha256 of where the entity came from (file path relative to the
      directory, plus row or group). Never collides; forced when ``params: null``.

## `artifacts`

One array child of every entity per entry.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | str | **yes** |  | Name of the array; becomes its key under the entity. |
| `dataset` | str | **yes** |  | HDF5 path of the array: absolute for 'files' and 'batch', relative to each entity group for 'groups'. |
| `optional` | bool | no | `False` | True if some entities lack this array; it is skipped for them. Otherwise a missing array is an error. |

## `shared`

Arrays identical for every entity, registered once as array children of the dataset
container and announced on its metadata as `shared_dataset_<type>`.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | str | **yes** |  | Name of the array; becomes its key under the dataset container. |
| `dataset` | str | **yes** |  | Absolute HDF5 path (in every source) of an array identical for all entities. Read from the first file that holds it; every other file must agree. |

## Migration from the `data:` / `parameters:` contract

| Before | Now |
|---|---|
| `data.layout: per_entity` | `source.files:` |
| `data.layout: batched` | `source.batch:` |
| `data.layout: grouped` | `source.groups:` |
| `data.directory`, `data.file_pattern`, `data.server_base_dir` | same names inside the tag; `file_pattern` is `pattern` |
| `parameters.location: root_scalars` | `params: {group: /}` (the default) |
| `parameters.location: root_attributes` | `params: {group: /, from: attrs}` |
| `parameters.location: group` + `group:` | `params: {group: ...}` |
| `parameters.location: group_scalars` + `entity_group:` | `groups.entity_group` + `params` relative to each entity group |
| `parameters.groups` / `recursive` / `exclude` | same names inside `params` |
| `provenance:` block | its fields directly under `metadata` |
| `extra_metadata` | `params.groups` |
| `tilewright stamp-key` | `tilewright manifest` writes `key` |

A YAML in the old shape gets one error naming this table.
