# Clarifications from the blind onboarding runs: field descriptions only

**Status:** accepted, 2026-09-17. Changes no field, no validator and no default of
ADR-0006's contract: every edit is to a `description` (or to a docs page), the one added
test pins behaviour rather than changing it, and the regenerated
`docs/reference/dataset-yaml.md` is the only generated file that moves.
Closes the documentation issues
[#13](https://github.com/slaclab/TileWright/issues/13),
[#25](https://github.com/slaclab/TileWright/issues/25),
[#26](https://github.com/slaclab/TileWright/issues/26),
[#27](https://github.com/slaclab/TileWright/issues/27),
[#28](https://github.com/slaclab/TileWright/issues/28) and
[#32](https://github.com/slaclab/TileWright/issues/32), raised from blind onboarding runs
over the public corpus of [#1](https://github.com/slaclab/TileWright/issues/1).

## Decision

Behaviour that the contract already has, and that authors had to discover by experiment,
is written down where the author looks. Each item below was reproduced against a fixture
before it was documented; the pull request carries the command and its output.

**`contract.py` descriptions** (no field, validator or default changes):

| Field | What it now states | From |
|---|---|---|
| `metadata.data_type` | a measurement of the world is experimental wherever the instrument stood; a model's output is simulation | #27 item 2 |
| `metadata.material` | a physical system that is not a substance is named as the system; `not_applicable` means no physical subject at all | #27 item 2 |
| `metadata.producer` | in a chain of codes, the last one that shaped the arrays | #27 item 2 |
| `metadata.description` | what counts as a number, and that nothing checks the rule | #27 item 1 |
| `label` | `slug()` keeps A-Z and 0-9, so a non-ASCII letter becomes `_`; a label with none at all is an error | #27 item 3 |
| `artifacts` | the list is what the dataset serves, not an inventory of the file | #27 item 7 |
| `artifacts[].type` | types are compared exactly: `gain_a` and `Gain_A` are two arrays | #27 item 5 |
| `shared` | 'axis' is the common case, not the rule: any array belonging to the dataset rather than to an entity goes here, a normalization or lookup table included, and nothing of an axis is required of it | #26 item 7 |
| `shared[].dataset` | a file that lacks the path is passed over, so per-entity group names cannot be shared; nothing is claimed about the values | #26 comment 2 item 1, #27 item 6 |
| `params.from` | attribute values are read whatever they hold; one block reads one way, and a source has one block | #26 items 1 and 3 |
| `params.recursive` | the key is the path, so a field kept as a group gives `<field>.data`, and nothing renames it; and the guarantee below the group is the cross-file one, the sibling-entity half being about names (see the last row) | #26 comment 2 item 2, this PR's review |
| `params.location` | a block holding only `location` is complete | #26 item 5 |
| `table.path` | every column is kept, an empty header cell included (`Unnamed: 4`); there is no filter | #32 item 2 |
| `table.id` | a null cell is allowed and hashed, and cannot be found by an equality search | #32 item 3 |
| `source.groups.params` | what the closed-group set closes is a member's own **name**: a name that resolves to a sibling entity group, or to a group `entity_group` matched, is warned about and skipped, and a target path that runs *through* such a name is followed, the sibling's values entering these parameters and this uid | this PR's review |

**Pages:** `reference/manifest.md` (what an attribute describes, types and nulls,
`config_hash`, the reserved-name list, what `file_size`/`file_mtime` describe, and what a
`uid` or `source_group` field read out of a file does to its column),
`reference/errors.md` (dumping a file that uses hard links, the HDF5 signature check, the
reserved artifact-attribute names, which now link to `manifest.md` instead of being listed
a second time, and what the entity-group warning row's cause really is),
`reference/cli.md` (what `--max-workers` counts),
`explanation/sources.md` (what a `table` can and cannot express, writing the table
yourself), `explanation/nexus.md` (files with no `@default`, one entity over several
files, a virtual dataset's dtype), `host-a-server.md` (a whole pointer-serving config,
embedded from `includes/config-pointer.yml`), `ONBOARDING.md` (how long a pointer run
takes, `--max-workers`; a read-back that scales), `using-the-catalog.md` (why to count
entities from the key list), and the onboarding `SKILL.md` (the authoring decisions).

## Why

Thirty-two public datasets were onboarded by agents that had read only the contract
surface. Where the surface was silent they guessed, and the guesses were mostly right —
which is the problem: the behaviour was already settled, so the only thing missing was the
sentence. Changing behaviour to match the guesses would have been the larger, riskier
change; stating it costs a description.

Three items are not written down as their issue states them:

- #26 item 1's example of a `batch` artifact row carrying `_ARRAY_DIMENSIONS
  ["water_year", "y", "x"]`. At the head this branch was first written against, an
  array-valued attribute never reached an artifact node, so the example could not happen.
  ADR-0013's PR (#31) then made a label and an artifact node's metadata carry what
  `from: attrs` carries, an array attribute as its list, and the example became true. The
  `manifest.md` table row that decision wrote is the home for *which values* are carried;
  what this PR keeps there is the half that decision does not state — that under `batch`
  the attributes are the stacked dataset's, so an attribute describing the stack's shape
  does not describe the row beside it, and that nothing interprets a value.
- #13 items 1-3 and #26 item 6 needed nothing: commits `74b3334` and `dc75d1c` had already
  put them in `params.group`, `params.exclude`, `pattern` and `batch.params`, after the
  surface revisions the issues quote. They were re-verified rather than re-stated.
- A parameter *dataset* named `uid` takes the manifest's own column rather than being
  refused as a `params.location` group of that name is, and a `source_group` dataset
  overwrites that column the same way; both run silently to exit 0. `manifest.md` now
  states that and tells authors to rename the field or `exclude` it, but making either an
  error would be a validator change, so what to do about it is
  [#41](https://github.com/slaclab/TileWright/issues/41) and not this PR.

## Consequences

- `tests/test_contract.py::test_concept_budget` is unchanged: it pins field names, and no
  name moved.
- Two existing tests pin description sentences
  (`test_the_data_type_description_lists_the_vocabulary_ids`,
  `test_the_from_description_says_what_differs_between_files`). Both still pass unchanged:
  the new sentences were written around them, not through them.
- `includes/config-pointer.yml` is a second config in the repository, invented rather than
  copied so that it carries no deployment's storage roots. `tests/test_docs_config.py`
  keeps its shape and its adapter line in step with `config.yml`.
- The onboarding skill grew; it is the home for decisions an author makes, and the facts
  themselves stay in the pages, linked.
- [ADR-0013](0013-recursion-stays-in-the-subtree.md) is amended rather than superseded: its
  hard-link bullet said "a link to one of them is named and skipped", which is a notch
  stronger than the code, and its residual list grows from two cases to three. The rule and
  the code are unchanged; only the description of what the rule leaves standing moves. The
  same over-claim had three other homes on the surface, all corrected here and all pinned
  by `TestRecursionStaysInTheSubtree::test_a_target_path_running_through_a_skipped_hard_link_is_followed`:
  `GroupsSource.params` and `ParamsSpec.recursive` (the two table rows above) and the
  entity-group warning row of `reference/errors.md`.
