# Reference pages follow the decisions an agent makes

**Status:** accepted, 2026-09-18. The second half of
[#48](https://github.com/slaclab/tilewright/issues/48), after ADR-0018 moved the pages into
the skill with their text unchanged. Changes three field descriptions (`method`,
`producer`, `description`) and no field.

## Decision

**One reference page per decision, read when the decision comes.** `skills/onboarding/
reference/` holds `source-and-entity`, `params-and-identity`, `artifacts-and-shared`,
`metadata-and-vocabulary`, `paths-and-server`, `nexus`, `netcdf-cf`, `counts-and-cost` and
`troubleshooting`, beside the generated `dataset-yaml` and the `manifest` reference. Each
opens with "Read this when…". The walkthrough keeps the six steps and the tested read-back,
and routes to the pages. Rationale ("why only four sources") moves to a closing
`Background` section of its page, where an agent can stop reading.

**`SKILL.md` routes; it does not restate.** Step 0 reads `contract.py` and the
walkthrough's steps, then a table says which page to read at which step. Step 2 is a
six-item checklist in the order the decisions are made, each item linking its page; the
~170 lines of cases it used to carry live in the pages. Field facts stay in `contract.py`
and the page generated from it.

**A slow-source gate before sign-off.** Step 3 predicts nodes (entities × artifacts per
entity). Above about 10,000 nodes, or 1,000 artifacts in one entity, the agent puts the
node count, a rough time and three choices to the owner in Step 4: register everything,
register a subset, or ask the producer to convert. TileWright builds no derived files; the
page gives the method for timing a run, not a rate, because the rate depends on the server
and is expected to change.

## Why

The pages were written for a person reading `docs/` in order. An agent reads the whole
skill before it knows what the dataset needs, so every NeXus rule, every netCDF placeholder
and every table case competed for its attention on every dataset. Splitting by decision is
what the progressive-disclosure pattern for skills asks for, and it matches how the blind
runs stumbled: across sources (parameters, server paths, keys), not per source.

The gate comes from one dataset that kept each day as its own array: 74,827 artifacts per
entity, about 21 hours to register, discovered only at `register`. The decision belongs to
the owner and before sign-off, so the skill raises it where the counts are predicted.

The blind runs on PR #47 also found gaps that no page covered, now filled: an array path
that changes from file to file (openPMD's `/data/<iteration>/`) means a `groups` source; a
tie between sources also weighs read cost; a parent group's attributes and attribute-only
records do not travel with the arrays; a simulation's method is its numerical technique;
a post-processor as `producer` hides the model from a search, so the model gets a key of
its own; a dimensionality in a description is prose.

## Consequences

- A fact that needs saying goes on the page for the decision it informs. If it informs
  none, it is background.
- `tests/test_skills.py` checks every link and anchor between the pages, that every page
  opens with "Read this when", and that `SKILL.md` routes to every page: a page it does
  not name is never read.
- A blind run after this change checks that the agent opened the pages its dataset needed
  and no others.
