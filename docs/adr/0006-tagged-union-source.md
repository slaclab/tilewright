# The dataset source is a tagged union

**Status:** accepted, 2026-09-09. Supersedes the `data:` / `parameters:` shape; ADR-0001's
frozen set of shapes still holds, now as four tags.

## Decision

A dataset YAML declares where its entities come from as one `source` block holding exactly
one tag, `files | batch | groups | table`, and each tag accepts only the keys that mean
something for it. `directory`, `server_base_dir`, `identity` are common; `pattern`,
`params`, `entity_group`, `path`, `id`, `locator` belong to the tags that use them.
`table` is new: the rows of a sidecar table are the entities and there are no arrays, for
data Tiled cannot read.

## Why

The previous contract had `data.layout` (three values) and `parameters.location` (four
values) as independent fields, twelve combinations of which only some made sense, held
apart by validator rules and a prose matrix in the reference. A reader of one layout had
to hold the whole matrix in mind. With the tag owning the keys, an illegal combination is
unrepresentable rather than rejected, and a reader of `batch` reads the `batch` keys and
nothing else. The minimal rebuild (`carbonscott/tilewright`) proved the shape on the same
corpus; the blind-agent trials there reproduced the legacy counts cold.

The pydantic models stay the single source of truth (the reference page is generated from
them), and every error is rendered as one sentence naming the field, all problems at once.

## Consequences

- The eleven YAMLs from the 2026-08-24 workshop are in the old shape; the reference carries
  a migration table and a YAML in the old shape gets one error naming it.
- `tests/test_contract.py::test_concept_budget` pins the top-level keys and the tags. A
  fifth tag needs real data none of the four can describe, and an ADR.
- `extra_metadata` and `provenance` are gone as top-level keys; `params.groups` and
  `metadata` cover them.
