# TileWright

A config-driven system for registering multi-entity scientific HDF5 datasets into a Tiled
catalog so they can be consistently registered and discovered. TileWright is
**dataset-agnostic** but **not structure-agnostic**: producers shape their data to one of
a small, fixed set of supported sources.

## Language

### Hierarchy

**Dataset**: a top-level container with facets (method, material, producer, contact,
description). Holds entities. _Avoid_: collection, repo.

**Entity**: a container whose physics parameters are queryable metadata; the unit a query
selects. In a `batch` source it is a row by default or, with `entity: file`, the file.
_Avoid_: sample, record, row.

**Artifact**: an array child of an entity (a spectrum, an image). The thing arrays load
from. _Avoid_: observable (the physics word), output.

**Shared axis**: an array identical for every entity, registered once as an array child of
the dataset and announced as `shared_dataset_<type>`.

These are nested Tiled **containers**; an entity's parameters are a **free-form metadata
dict**, not declared columns (ADR-0004).

### The contract

**Dataset YAML**: the per-dataset file, `<data root>/.tilewright/datasets/<KEY>.yml`,
declaring label, metadata, source, artifacts, shared. The authored input; the Parquet
manifest is the output.

**Source**: where entities come from, one of exactly four tags (ADR-0006): `files` (one
file per entity), `batch` (stacked on axis 0), `groups` (one group per entity), `table`
(rows of a sidecar table, no arrays). Each tag owns only its keys. _Avoid_: layout, format.

**Row parameter**: a 1-D dataset with one value per row of a file entity (`row_params`).
Listed in the field dictionary, never expanded into entities.

**Field dictionary**: `fields`, stamped on the dataset: one entry per parameter, row
parameter, artifact and shared axis, with role, dtype, HDF5 path and shape. What a
consumer reads before opening a file.

**Identity**: how an entity's uid is computed (ADR-0007). `params` (default): a hash of
parameter values. `provenance`: a hash of file path plus row or group; forced when there
are no parameters. Duplicate identities fail the manifest.

**Key**: the dataset container key, `slug(label)`, written by `tilewright manifest`.

**Fingerprint**: a hash of which data a YAML describes (tag, server-visible directory,
pattern, params, identity), stamped on the container; `register` refuses a different
fingerprint under the same key.

**Vocabulary**: canonical ids and aliases for the facets, in `vocabulary.yml`. Soft:
unknown values warn (ADR-0003). Grows by pull request. _Avoid_: schema, semantic model.

**Contract surface**: the artifacts that define a valid dataset: `contract.py`, the
generated YAML reference, `vocabulary.yml`, `examples/datasets/*.yml`,
`docs/ONBOARDING.md`. Onboarding reads the surface, never the implementation.

### Commands

**`tilewright manifest`**: validate the YAML, write the key, scan the data, write the two
Parquet manifests. _Avoid_: generate, stamp-key, inspect.

**`tilewright register`**: manifests → server over HTTP; the single route (ADR-0002).
Pointer by default, `--upload` streams arrays; `--update` merge-patches dataset metadata.

**Transport**: `external` (the server reads the files) or `uploaded` (the server holds the
bytes); a dataset is one or the other.

**Read paths**: through the server, or straight from the files via locators. _Avoid_:
Mode A, Mode B.

## Relationships

- A Dataset contains Entities; an Entity contains Artifacts; a Dataset may hold Shared axes.
- A Dataset YAML describes exactly one Dataset and declares its Source and Identity.
- The Vocabulary constrains the facet values of every Dataset; the Contract constrains its
  shape.
