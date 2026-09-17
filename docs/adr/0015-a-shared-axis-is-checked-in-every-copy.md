# A shared axis is checked in every copy the source holds, not once per file

**Status:** accepted, 2026-09-17. Settles
[#37](https://github.com/slaclab/TileWright/issues/37). Reads `shared:` against ADR-0011's
entity groups; changes no field of the contract, only what the tool checks and what
`SharedAxisSpec.dataset` promises. Keeps ADR-0007's identity rule: a shared axis has no
uid and takes no part in an entity's identity, so nothing here moves a uid or a
fingerprint.

## Decision

**A `shared:` entry names one copy of an array, and `tilewright manifest` compares it with
every other copy the source holds.** Which copies the source holds follows from its tag:

- `files`, `batch`, `table`: the named path, once in each file — as before;
- `groups`: the named path lies inside one entity group, so **each entity group of each
  file holds its own copy**, at the same path relative to its own group. One file with
  four entity groups holds four copies, and all four are compared. A path *beside* the
  entity groups (a calibration group next to them) is one copy per file, as under the
  other tags.

The row written into the manifest is unchanged: the array at the path the entry names, in
the first file that holds it. The other copies are read to be compared and nothing else.
Two copies that differ are refused, and the message names the axis and **both** locations,
each as `<file>:<path>`:

```
shared axis 'energy' (/scan/point_01/energy) differs between scan.h5:/scan/point_01/energy
and scan.h5:/scan/point_02/energy; a shared axis must be identical in every copy the
source holds. If it varies per entity, list it under 'artifacts:'.
```

## Why

The check was written for the `files` shape and read `ax.dataset` once per file. A
`groups` source over **one** file therefore compared nothing at all: one copy was read,
`shared=N` was reported, and every entity but the one whose copy was named was served an
axis that was not its own. The contract promised the opposite — "an array identical for
all entities" — and the only way an author could keep that promise was to digest every
array by hand before writing the YAML. Two independent onboarding workers did exactly
that, one of them on a single file with four entity groups holding four copies of each of
eight axes.

The alternative was to say in the reference that under `groups` the entry is trusted and
not checked. That would have been honest but useless: the failure it leaves is silent, and
what it serves is wrong per entity, which is the one thing the hierarchy exists to get
right.

## Consequences

- A YAML that was accepted before can be refused now, and that is the point: it was
  refused because the copies genuinely differ, which means the array is an artifact, not
  an axis. Nothing that was already registered changes; re-running `manifest` over a
  dataset whose copies agree writes the same rows, with the same uids and the same
  fingerprint.
- `manifest` reads more arrays under `groups` — one per entity group per shared entry
  rather than one per file. They are read in full, because comparing them is the point;
  an axis is a one-dimensional array, and the cost is the same as reading the artifacts
  beside it.
- The fact has one home, `SharedAxisSpec.dataset`, which the YAML reference is generated
  from; `docs/reference/errors.md` carries the message, with both shapes of the "differs
  between" line.
- Tests: `tests/test_manifest.py::TestGroups::test_shared_axis_copies_in_every_entity_group_must_agree`
  (identical copies manifest, a differing sibling is refused naming both) and
  `::test_a_shared_axis_beside_the_entity_groups_is_one_copy_per_file` (the rule is not
  applied where it does not belong).
  `TestBatch::test_shared_axis_must_agree_across_files` keeps the between-files case.
