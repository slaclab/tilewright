# Identity and keys

Three things in the catalog have to be stable and unambiguous: a dataset's key, an
entity's key, and which data a dataset container describes. Each is derived, not chosen.

## The dataset key comes from the label

You write `label: Okafor NiPS3 Powder`; `tilewright manifest` writes
`key: OKAFOR_NIPS3_POWDER` into the YAML. The rule is uppercase with runs of anything
else collapsed to one underscore. A key that no longer matches its label is an error,
never a silent rewrite, because the old key may already hold registered data.

Two people who pick the same label get the same key. What keeps that from merging their
data is the fingerprint.

## The fingerprint says which data a container holds

`tilewright manifest` hashes the facts that identify *which data* a YAML describes: the
source tag, the directory as the server sees it, the file pattern or table path, the
params spec, the identity mode, and a table's `id` when it is a list. Not the label, not
the metadata. The hash goes into the manifest, and `tilewright register` stamps it on the
dataset container as `fingerprint`.

When the key already exists on the server:

| The container's fingerprint | What `register` does |
|---|---|
| matches | proceeds; existing entities are skipped, new ones added. With `--update`, the YAML's metadata is merge-patched in first, and Tiled keeps the previous version as a revision |
| differs | refuses, prints both fingerprints and the container's label and description, and asks for a different label |
| absent (registered before fingerprints) | refuses unless `--adopt`, which stamps it |

Copying the same files to a new directory and re-registering under the old label is the
"differs" case. A rename is cheap; silently merging two copies would not be.

## The entity key comes from the entity's identity

An entity key is `<DATASET_KEY>_<uid[:13]>`, and the uid is a hash. Of what depends on
the source's `identity`:

**`params`** (the default): a hash of the parameter *values*. The same physics is the same
entity across re-registration and file moves, which is what a simulation sweep wants and
what makes re-running `register` safe. The cost is that two entities with identical
parameters would collide, so `tilewright manifest` refuses that, names the colliding
entities, what differs between them and the parameters they share, and offers the two
fixes: add a distinguishing parameter, or switch identity.

**`provenance`**: a hash of where the entity came from, the file path relative to the
directory plus its row or group. It never collides unless `pattern` or `entity_group`
matches the same thing twice. It is forced when a source declares `params: null`, and it
is the right choice for run-oriented experimental data where repeated measurements share
every setting. Moving the whole directory changes nothing; renaming a file inside it
changes that entity's key.

These two modes belong to the HDF5 sources (`files`, `batch`, `groups`). Nothing about
identity appears in their YAML unless you write `identity: provenance`.

**A table's identity is its `id` column(s).** A `table` source has no `identity` key. One
column, `id: run_number`, hashes that column's value; a list, `id: [system_id, tilt]`,
hashes the list of values, for a table where no single column is unique. Rows that
repeat the id values collide like any other entities: the report shows the columns that
tell them apart, and one of those goes into the list. A table whose rows are equal in
every column has no identity to find, and has to be de-duplicated.

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

## What a rerun can and cannot see

`register` never opens a file, so it cannot tell whether an array changed. What it can
compare is the modification time and size the manifest recorded against the ones stamped
on the array node when it was registered. A mismatch on a skipped artifact is reported as
changed on disk, the command exits non-zero, and nothing is rewritten: the fix is
regenerate, delete, register. Under `params` identity a regenerated file with the same
parameters would otherwise be skipped silently and the catalog would serve the old bytes;
this check is what stops that.

## What is deliberately not identity

Attribute labels (`Ei_units`) are stored beside a parameter but never hashed, so fixing a
units string does not create a new entity. Dataset-level metadata is not hashed either;
that is what `--update` is for.

See also [the manifest reference](../reference/manifest.md) for the exact columns, and
[the `identity` field](../reference/dataset-yaml.md#identity).
