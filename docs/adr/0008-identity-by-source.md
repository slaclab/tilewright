# Identity follows the source: a table is identified by its id columns

**Status:** accepted, 2026-09-17. Amends ADR-0006 (`identity` is no longer common to every
tag) and ADR-0007 (a table's identity is not provenance). Decided in the public comments
on [#6](https://github.com/slaclab/TileWright/issues/6#issuecomment-5710338438) and
[#9](https://github.com/slaclab/TileWright/issues/9#issuecomment-5710338651).

## Decision

**`identity` and `pattern` belong to the HDF5 sources.** The two keys, which `files`,
`batch` and `groups` defined alike, move from the base every source shares into a base
for those three. A `table` has neither, so `identity:` under a table is reported as "not
a contract key". This is ADR-0006's rule applied once more: a tag owns only the keys that
mean something for it.

**A table's identity is its `id` column or columns.** `TableSource.id` takes one column
or a list of columns.

- One column keeps the uid a table has always had, `sha256('<KEY>:' + str(value))[:16]`,
  so tables that are already registered are not re-keyed.
- A list hashes `'<KEY>:'` followed by the JSON list of the values,
  `sha256('<KEY>:' + json.dumps([v1, v2, ...]))[:16]`. A one-element list is a list: it
  keys differently from the same column written as a string.
- The reference renders the type as "str or list of str".

When no set of columns is unique, the rows are equal in every column and the table has
to be de-duplicated. The contract does not invent a row number.

**The collision report names what differs.** For every uid that several entities share,
`tilewright manifest` prints where each came from (for a table, the id values and the row
numbers), then each column or parameter whose values differ, with one value per entity;
under `identity: params` it also prints the parameters they share. Duplicates stay an
error. The `Fix:` line depends on the source:

- `table`: list one of the differing columns in `id` (an example list covers every
  shared uid); rows equal in every column must be de-duplicated;
- `files`, `batch`, `groups` under `provenance`: `pattern` or `entity_group` matches the
  same thing twice;
- under `params`: add a distinguishing parameter, or set `identity: provenance`.

**A batch source may declare `params: null`.** `BatchSource.params` becomes optional with
the meaning it already had for `files` and `groups`: the entities have no parameters and
identity becomes `provenance`.

**Two implicit behaviours are now written in the contract** (from #13):

- the `pattern` description states the glob dialect as implemented (F15): `Path.glob`
  relative to `directory`, `*` within one path segment, `**` recursing, dot names matched
  like any other, no braces, and a pattern that matches nothing retried with `rglob`.
  The fallback is documented, not removed;
- the `BatchSource.params` description states the batch rule (F16): only 1-D members of
  length N are per-entity values, 0-dim members are broadcast, and anything else, `(N, 1)`
  included, is skipped without a message.

**The fingerprint does not move.** `source_fingerprint` hashes the same facts as before;
for a table the identity mode it hashes is still `provenance`, which is also what the
manifest's `identity` metadata records. A test pins the fingerprint of every example YAML,
and of six identity and params variants, to the values computed before this change.

## Why

The contract said three different things about a table. `Identity.provenance` promised
"file path plus row" and "never collides"; `TableSource.id` said the column "is the
entity's identity"; the code hashed the id value alone. So a table whose id repeated
(osti/1846021, 1,862 PV systems where two `system_id`s appear twice and no column is
unique) failed with a report that hid the value telling the rows apart and advised fixing
a `pattern` or `entity_group` the table does not have. The remedy `errors.md` gave,
`identity: provenance`, changed nothing. Choosing the column is what the author can
actually do: the colliding rows there look like two arrays at one site, told apart by
`tilt` and `azimuth`, and a composite id says so.

A `batch` file can hold no per-entity values at all (osti/1787546: waveforms and station
positions, nothing else). `errors.md` offered `params: null` for "no parameters found"
without naming a source, and a batch source rejected it; the only way out was to point
`params` at the root and exclude every member.

**The argument that lost: row-number provenance for tables.** Hashing the table path plus
the row number never fails, needs no new key, and matches the old `Identity` docstring
("plus row") literally. It lost because a table gets edited: re-sorting it re-keys every
entity, and inserting or removing a row re-keys every row after it, so a re-registration
under the same fingerprint would add those entities a second time. An id column moves
with its row.

## Consequences

- A YAML with `identity:` under `table` no longer validates. It never had an effect.
- Existing single-column tables keep their uids and fingerprints; no dataset is re-keyed.
- Changing `id` re-keys every entity of the table. The fingerprint does not include `id`
  (it did not before), so re-registering under the same label after such a change adds
  the entities again: delete the dataset first.
- `tests/test_contract.py::test_concept_budget` now pins each tag's keys and the keys of
  `params` and of an artifact entry; every later contract change edits that one test.
- `tests/test_contract.py::test_batch_params_cannot_be_null` asserted the behaviour this
  decision reverses; it became `test_batch_params_null_forces_provenance`.
