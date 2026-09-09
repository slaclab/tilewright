---
name: vocab-review
description: >-
  Maintainer task: find the metadata values on a live Tiled server that are not in
  TileWright's vocabulary, decide for each whether it is an alias of an existing id or a
  new id, edit src/tilewright/vocabulary.yml, and open a pull request. Use before a release,
  after a workshop, or when someone asks "what values are people actually using". Never run
  during dataset onboarding.
---

# Reviewing the vocabulary against a server

The vocabulary (`src/tilewright/vocabulary.yml`) grows by pull request, never at
registration time. Datasets register with whatever value the author wrote; this task is how
a recurring value becomes a canonical id, so `Key("material") == ...` finds every dataset
that meant the same thing.

## 1. Run the report

```bash
uv run scripts/vocab_report.py --url <URL> --api-key <KEY>
```

It asks the server for the distinct values of every facet across the dataset containers
(one `distinct` query per facet, no walk), diffs them against the packaged vocabulary, and
prints the off-list values with a count and one example dataset key. It writes nothing.

## 2. Decide, per off-list value

Read the example dataset's metadata (`from_uri(URL, api_key=KEY)["<KEY>"].metadata`) and
its description before deciding. For each value, exactly one of:

- **Alias of an existing id.** The author meant something already listed under a
  different spelling (`HRSTEM` → `STEM`, `PowderDiffraction` → `Diffraction`, `Mantid` →
  `mantid`). Add it to that entry's `aliases`. An alias changes spelling only; if the
  value carries extra meaning (EDRIXS is always a simulation), that stays the author's
  to write in `data_type`.
- **New id.** A genuinely new method, material, producer, facility, project or proposal.
  Add an entry with `id` (as authors will type it), a `label` (the full name), and for
  producers the `repo`. Keep ids short and stable; put alternative spellings in `aliases`.
- **Leave it.** A one-off that should not be promoted (a typo the author will fix, a value
  that belongs in `description`, a proposal id nobody else will query). Say so in the PR.

Ask the maintainer when a value could be either an alias or a new id — that judgment is
theirs. Do not add a facet: which fields exist is defined in `contract.py`, and adding one
is a contract change with its own review.

## 3. Edit and prove

- Edit `src/tilewright/vocabulary.yml` only. Keep entries grouped by facet and roughly
  alphabetical after the ids already there.
- `uv run --extra test pytest tests/test_contract.py tests/test_examples.py` — the
  examples must still validate with zero warnings, and alias resolution must still work.
- Re-run the report: every value you promoted should have left the off-list table.

## 4. Open the pull request

One PR per review. The description lists each promoted value with its decision (alias of
X / new id) and the dataset that motivated it, and names the values deliberately left
off-list. Aliases are cheap; ids are forever, since datasets already registered keep the
value they were registered with — say in the PR if any existing dataset should be
re-registered with `--update` to pick up a canonical id.
