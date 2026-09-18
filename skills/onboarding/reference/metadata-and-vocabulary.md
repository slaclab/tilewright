# Metadata and vocabulary

**Read this when** you draft the dataset's `metadata` (Steps 2 and 3): the facets a
reader searches by, where their values may come from, and how to spell them.

## Nothing fills `metadata` in from the files

`method`, `data_type` and `material` are required; `contact` and `description` are
expected. Every value comes from the data's owner, the codebase or context they named, or
you — never from the files by themselves. Dataset-level facts the producer left as HDF5
root attributes (`@title`, `@source`, `@institution`) never reach `metadata` by
themselves — a `params` block reads per-entity values, not dataset-level ones — so copy the
ones worth keeping into the YAML by hand, and say in the `description` that they came from
the files rather than from a person.

Read the codebase or context the owner named to infer `method`, `data_type`, `material`,
`producer`, `project`, `facility`, `instrument` and `proposal`, alongside the files' root
attributes.

What each facet means, and the cases the data rarely settles — `material` for something
that is not a substance, `method` for a simulation or for data no method produced,
`data_type` between `simulation`, `benchmark` and `optimization` for an enumerated set,
`producer` when a chain of codes made the files, and what counts as a number in
`description` — are decided in the field descriptions in `contract.py`
([rendered here](dataset-yaml.md#metadata)). Read the field before you guess.

## Spelling a value: the soft vocabulary

`Key("material") == "NiPS3"` is only useful if everyone spelled NiPS3 the same way. The
vocabulary is how that agreement is kept.

It is `vocabulary.yml` inside the installed package (`<pkg>/vocabulary.yml`; in a checkout,
`src/tilewright/vocabulary.yml`), and it defines canonical ids, plus aliases for them, for
seven facets: `method`, `material`, `producer`, `project`, `proposal`, `facility`,
`data_type`. Which *fields* exist is defined once, in the contract, not here.

Map each value onto a canonical id where one fits. Where none does, write the producer's
own term: that is not inventing vocabulary, it registers as written with a note, and the
curator sees it later. What you must not do is coin an official-looking id, stretch an
unrelated one, or edit `vocabulary.yml` (that is a maintainer's job, by pull request).

### Notes, not rejections

An unknown value warns and validates. The dataset onboards either way.

- A known alias is rewritten to its canonical id: `EDRIXS` becomes `RIXS`, `nips3` becomes
  `NiPS3`, `HRSTEM` becomes `STEM`. An alias changes spelling and nothing else. The
  rewrite happens each time the YAML is read, and the file keeps what you wrote. The
  exception is a YAML that `tilewright manifest` must write out whole to add its `key:`
  ([when](https://github.com/slaclab/tilewright/blob/main/docs/reference/cli.md#tilewright-manifest)): that file then holds the canonical ids.
- An unknown value is left as you wrote it, and `tilewright manifest` prints a note.

The fields `method`, `data_type`, and `material` must still be present. Only their values
are soft.

## Background

**Why notes and not rejections.** The stricter option would be to reject unknown values.
That fails badly for the first person to bring a new material: they cannot register
anything until someone edits a vocabulary file in a repository they may not have write
access to. In practice they would pick a term that does pass, and the catalog would record
something untrue. A warning gets the data in with the value the producer meant, and leaves
a record for whoever curates the vocabulary later.

**How it grows.** By pull request, from evidence. `scripts/vocab_report.py`, in the
TileWright repository, asks a live server for the distinct values of every facet, diffs
them against the vocabulary, and prints what is off-list with a count and an example
dataset. A person then decides, per value, whether it is an alias of an existing id or a
new id, writes the label, and opens the PR; the repository's `vocab-review` skill walks
through it. Nothing is promoted automatically, because the label, the aliases and the
implications are judgment. After one workshop the report showed fifteen off-list values across six facets:
six methods, five materials, three producers, one facility. Most became aliases or ids in
the next release. That loop, register freely and promote what recurs, is the vocabulary's
whole design.

**What drift costs.** Presence can be enforced. Agreement cannot, and this is where it
breaks down. Authors who have not read the vocabulary invent reasonable synonyms:
`PowderDiffraction` for `Diffraction`, `Mantid` for `mantid`, a proposal number in
`project`. None are wrong as English, and all are invisible to a query written against the
canonical id, without anything failing or anyone being told. The report exists to make
that drift visible.
