# The soft vocabulary

`Key("material") == "NiPS3"` is only useful if everyone spelled NiPS3 the same way. The
vocabulary is how that agreement is kept.

It lives in `src/tilewright/vocabulary.yml` and defines canonical ids, plus aliases for
them, for seven facets: `method`, `material`, `producer`, `project`, `proposal`,
`facility`, `data_type`. Which *fields* exist is defined once, in the contract, not here.

## Warnings, not rejections

An unknown value warns and validates. Your dataset onboards either way.

- A known alias is rewritten to its canonical id: `EDRIXS` becomes `RIXS`, `nips3` becomes
  `NiPS3`, `HRSTEM` becomes `STEM`. Some aliases imply a default too, so `EDRIXS` also
  implies `data_type: simulation`.
- An unknown value is left as you wrote it, and `tilewright manifest` prints a note.

The stricter option would be to reject unknown values. That fails badly for the first
person to bring a new material: they cannot register anything until someone edits a
vocabulary file in a repository they may not have write access to. In practice they would
pick a term that does pass, and the catalog would record something untrue. A warning gets
the data in with the value the producer meant, and leaves a record for whoever curates the
vocabulary later.

The fields `method`, `data_type`, and `material` must still be present. Only their values
are soft.

## How it grows

By pull request, from evidence. `scripts/vocab_report.py` asks a live server for the
distinct values of every facet, diffs them against the vocabulary, and prints what is
off-list with a count and an example dataset. A person then decides, per value, whether
it is an alias of an existing id or a new id, writes the label and any implied fields, and
opens the PR; the `vocab-review` skill walks through it. Nothing is promoted
automatically, because the label, the aliases and the implications are judgment.

After one workshop the report showed fifteen off-list values across six facets: six
methods, five materials, three producers, one facility. Most became aliases or ids in the
next release. That loop, register freely and promote what recurs, is the vocabulary's
whole design.

## What drift costs

Presence can be enforced. Agreement cannot, and this is where it breaks down. Authors who
have not read the vocabulary invent reasonable synonyms: `PowderDiffraction` for
`Diffraction`, `Mantid` for `mantid`, a proposal number in `project`. None are wrong as
English, and all are invisible to a query written against the canonical id, without
anything failing or anyone being told. The report exists to make that drift visible.

See also [the `metadata` section](../reference/dataset-yaml.md#metadata) for the fields
themselves.
