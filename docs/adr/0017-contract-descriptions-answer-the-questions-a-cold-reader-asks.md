# ADR-0017: Contract descriptions answer the questions a cold reader asks

## Status

Accepted.

## Decision

Five field descriptions in `contract.py` change. No field, validator or default changes;
behaviour is identical before and after.

1. **`source.groups.entity_group`** — its default is stated as the group the field names,
   not as the entities that result: "Default: the file root, so that each of the file's own
   top-level groups is an entity", with a parenthesis saying what the other reading (`/*`)
   would do instead.
2. **`metadata.data_type`** — `benchmark` and `optimization` get a sentence each, and the
   enumeration case gets a tiebreaker: a space computed or measured case by case, with
   nothing scoring or steering it, is `simulation` or `experimental` however exhaustive it
   is and whoever later grades a model against it.
3. **`metadata.method`** — says what to write when no method produced the data:
   `['not_applicable']`, the escape hatch `material` already documents, off-vocabulary for
   `method` and so registered with a note. It also rules out the three things authors put
   there instead: a field of study, a file format, a code name.
4. **`metadata.description`** — the "every number needs a key" rule gets one operational
   test ("would someone write `Key('...') == <that number>` to find datasets?") and three
   named edges: a key means a key of this `metadata` block and not an entity parameter; a
   number inside a token (`uint8`, `NiPS3`, a version, a DOI, a year in a name) is prose;
   a value quoted to explain what it means (`0 is a valid reading, not a gap`) is prose.
5. **`metadata.contact`** — says what to write when the record publishes no address: the
   name, and where it can be reached from.

`docs/reference/dataset-yaml.md` is regenerated from these.

## Why

A fresh agent was given `docs/ONBOARDING.md` and the contract surface at `9710623`, with
no issues and no source outside that surface, and asked to onboard a real dataset. It
succeeded — its predicted counts matched the manifest — but judged the document usable
"for the mechanics, yes; for the metadata facets, no", and every one of the five items
above is a question it could not answer from the page it was sent to.

Three of them were wrong or absent on the authoritative file while the derived files were
right. `entity_group`'s default read as naming the entity groups, which for a file whose
top-level groups are the entities would mean zero entities, while
`examples/datasets/groups.yml` and `reference/errors.md` both described the real
behaviour. Two of the four `data_type` ids existed only as bare ids in `vocabulary.yml`,
with no label there and no sentence anywhere. `method` is required with no vocabulary id
for "none", so an author with no method either invents one or writes something that is not
a method at all.

The alternative for items 2 and 3 was a vocabulary change: a `label` for `benchmark` and
`optimization`, an id for "no method". That is a different kind of change, made by the
`vocab-review` skill against evidence from a live server, and it would not have helped this
reader anyway — a label in `vocabulary.yml` still would not say when to choose the id.
Where the field's meaning is the question, the field description is the answer.

Item 4 was undecidable rather than absent: the rule read the same to an author whose every
number was in an entity parameter as to one whose numbers were dataset facts, and that
reader invented six dataset keys to be safe. A rule the surface cannot apply mechanically
is a rule that costs an author time in both directions, so it now carries its own test.

## Consequences

- Description-only, so `tests/test_contract.py::test_concept_budget` (which pins field
  names, source tags and top-level keys) is unchanged and still correct.
- `['not_applicable']` under `method` will start appearing on servers with a vocabulary
  note beside it. That note is the evidence the `vocab-review` skill runs on: if it
  recurs, promoting it to a `method` id is that skill's call, not this one's.
- The `description` rule now names `metadata` keys specifically. Authors who had been
  counting entity parameters as keys will write a dataset key or drop the number; both are
  what the rule always meant.
- `contract.py`'s `metadata` block is long enough that a reader meets it as a table of
  paragraphs. If it grows again, the answer is a separate explanation page for the facets
  with the fields linking to it, not shorter descriptions.
