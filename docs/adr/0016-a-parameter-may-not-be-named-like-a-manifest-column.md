# A parameter may not be named like a column the manifest writes itself

**Status:** accepted, 2026-09-18. Settles
[#41](https://github.com/slaclab/TileWright/issues/41). Extends ADR-0007's identity rule to
the one case that could override it silently; changes no field of the contract, only what
`tilewright manifest` refuses and what `ParamsSpec` promises.

## Decision

**`uid` and `source_group` are the manifest's own, and nothing a dataset carries may be
named like one of them.** `tilewright manifest` refuses the run, naming the file, the
parameter and what to do, wherever such a name arrives:

- a scalar dataset or an attribute read as a parameter, under any source tag and under
  both `from: datasets` and `from: attrs`;
- a `params.groups` name, since every key of that group nests under it (`uid.tenDq`) and
  registration nests the metadata the same way;
- a `<field>_<attr>` label — a parameter `source` carrying an attribute `group` spells
  `source_group` without either name being one;
- a column of a `table` source, which already refused `uid` and now refuses
  `source_group` with it;
- a named group of `params.location`, which the contract refused before this ADR and
  refuses unchanged.

A dotted name counts as its first part, so a *nested* key is refused only when the name it
nests under is one of the two: `meta.uid` from `params.groups: {meta: /meta}` is an
ordinary column and stays one. That is also the fix that keeps the value; the others are
`params.exclude` and renaming the field in the file.

The list lives in one place, `ENTITY_COLUMNS` in `contract.py`, which both the contract's
`params.location` validator and the walker read. Artifact-table column names (`type`,
`file`, `dataset`, `index`, `shape`, `dtype`, `file_size`, `file_mtime`) are **not**
reserved for an entity parameter: they are reserved one level down, for an array's own
attributes, where `_attrs` drops them with a warning. A parameter called `event`, `size`
or `dataset` stays an ordinary column, and four of the thirty-two datasets this campaign
registered carry such a name.

## Why

The params reader turns every scalar of the group into a column and the walker merged
those columns into the entity row *after* the standard ones, so a parameter whose name
equalled a standard column won. A file carrying `/meta/uid` therefore replaced the
identity `tilewright manifest` had just computed with the number the file happened to hold,
and `/meta/source_group` replaced the group each entity was read from, both with exit 0 and
no message. The uid decides the entity key, the incremental skip and what a later run
treats as the same entity, so two entities could collide, or a re-run could register beside
the existing nodes instead of skipping them.

The issue offered a second fix: keep the parameter, under a name that does not collide,
and say so once per run. Refusing was chosen for three reasons.

1. **Identity must be a function of what the file says.** A parameter is hashed into the
   uid, its name included. Carried under a name TileWright invented, a value would be
   hashed under a key no file and no YAML spells, and a later change to that escape would
   move every uid of every dataset that ever had the collision.
2. **The contract already says nothing renames a key** ("the parameter a reader queries is
   the one the file spells", `ParamsSpec.recursive`). A silent rename would make that
   sentence false in exactly the case an author is least likely to check.
3. **Every neighbouring rule is a refusal**, and the same names are among them: the
   contract refuses `uid` and `source_group` as `params.location` groups, refuses a
   `location` group starting with `_`, refuses a locator-shaped parameter name, and a
   `table` already refused a `uid` column. A fourth behaviour for the same kind of
   collision would be a rule more to learn and a warning more to miss.

The cost of refusing is that a dataset genuinely carrying such a field must say one line
about it. That line can keep the value: nesting its group under a name of the author's own
turns `uid` into `meta.uid`. It renames that group's other parameters too, and so moves the
dataset's uids — which is why it is offered as the way to *keep* a value, never applied
silently.

## Consequences

- A YAML that was accepted before can be refused now. No dataset registered by this
  campaign is affected: all thirty-two re-manifest with identical uids and fingerprints
  (evidence in the pull request), every one of their `uid` columns is the 16-hex
  identifier TileWright computed, and no YAML or table column names either word.
- The identity column is TileWright's own under every tag, which is what the incremental
  skip and `--append` rely on.
- The message is the locator message's twin: same shape, same `Fix:` derivation, one
  sentence different, so `reserved_error` builds both rather than growing a second
  message-builder.
- The fact has one home, `docs/reference/manifest.md`, "Reserved names", which now carries
  a row per place a name can arrive; the author-facing half is in `ParamsSpec.group` and
  `ParamsSpec.groups`, which the YAML reference is generated from, and the messages are in
  `docs/reference/errors.md`.
- Tests: `tests/test_manifest.py::TestReservedNames::`
  `test_a_files_parameter_named_like_a_manifest_column_is_refused`,
  `test_an_attribute_named_like_a_manifest_column_is_refused`,
  `test_a_batch_parameter_named_like_a_manifest_column_is_refused`,
  `test_a_groups_parameter_named_source_group_is_refused`,
  `test_a_params_groups_name_that_is_a_manifest_column_is_refused`,
  `test_a_label_that_spells_a_manifest_column_is_refused`,
  `test_a_table_column_named_like_a_manifest_column_is_refused`, and
  `test_a_params_groups_name_of_your_own_still_nests_such_a_field`, which holds the guard
  open: the rule reaches a key's first part only.
