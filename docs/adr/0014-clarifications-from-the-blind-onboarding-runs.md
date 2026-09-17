# Clarifications from the blind onboarding runs: field descriptions only

**Status:** accepted, 2026-09-17. Changes no field, no validator and no default of
ADR-0006's contract: every edit is to a `description` (or to a docs page), and the
regenerated `docs/reference/dataset-yaml.md` is the only generated file that moves.
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
| `shared[].dataset` | a file that lacks the path is passed over, so per-entity group names cannot be shared; nothing is claimed about the values | #26 comment 2 item 1, #27 item 6 |
| `params.from` | attribute values are read whatever they hold; one block reads one way, and a source has one block | #26 items 1 and 3 |
| `params.recursive` | the key is the path, so a field kept as a group gives `<field>.data`, and nothing renames it | #26 comment 2 item 2 |
| `params.location` | a block holding only `location` is complete | #26 item 5 |
| `table.path` | every column is kept, an empty header cell included (`Unnamed: 4`); there is no filter | #32 item 2 |
| `table.id` | a null cell is allowed and hashed, and cannot be found by an equality search | #32 item 3 |

**Pages:** `reference/manifest.md` (which attribute values are carried, types and nulls,
`config_hash`, the reserved-name list, what `file_size`/`file_mtime` describe),
`reference/errors.md` (dumping a file that uses hard links, the HDF5 signature check),
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
  ["water_year", "y", "x"]`: an array-valued attribute never reaches an artifact node. The
  true statement (labels and artifact metadata keep text and numbers only, and under
  `batch` they are the stacked dataset's) is what `manifest.md` now carries.
- #13 items 1-3 and #26 item 6 needed nothing: commits `74b3334` and `dc75d1c` had already
  put them in `params.group`, `params.exclude`, `pattern` and `batch.params`, after the
  surface revisions the issues quote. They were re-verified rather than re-stated.
- A parameter *dataset* named `uid` takes the manifest's own column rather than being
  refused as a `params.location` group of that name is. `manifest.md` now tells authors to
  rename it, but making it an error would be a validator change, so it is left to its own
  issue.

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
