# Recursion stays inside the params group's own subtree

**Status:** accepted, 2026-09-17. Narrows ADR-0011's recursion rule (recursion never
enters an entity group or a matched group) and settles
[#34](https://github.com/slaclab/TileWright/issues/34) after four rounds of review;
keeps ADR-0007's identity rule (only what is read is hashed) and ADR-0011's refusal of
`recursive` together with a `..` path. Decided by the fix campaign's orchestrator after
the fourth review of the rule, on the three leaks below, and amended after the fifth,
which defeated the first form of the test with one extra hop and showed that a linked
dataset below the group was still read out of the subtree.

## Decision

**`params.recursive` follows only what lies inside the subtree of the group it reads, and
the rule stops at the group the author named.** That group's own members are read as they
are without `recursive`, a link written there followed wherever it leads; the descent
below it — into a subgroup, and everything read under one — follows only what lies inside
the subtree, **subgroups and datasets alike**. A member that leads out is named in a
WARNING and skipped:

```
  WARNING: /data/station_a.h5:/runs/day/peek links to /data/station_a.h5:/runs/night/readout, outside the group being read (/runs/day); skipped
```

The target is placed from the link, not from the path the reader opened it through
(`h5py` reports the opened path for a linked object, so `Group.name` cannot say where a
link led), and a **chain** of links is followed to its final target:

- an **external link** resolves in another file, so it is never inside the subtree. The
  warning names that link's own file — made absolute against the file that holds it, as
  HDF5 resolves a relative one — and its own path, so a soft link that reaches it does
  not pair the target file with a path in the source file;
- a **soft link**'s target path, resolved against the group that holds the link when it
  is relative, must be the group the walk started from or one under it, in that file.
  When it is, whatever lies at that path may be a link in turn, and the chain goes on
  there: a test of one link's own target passes at `hop` in
  `hop -> direct -> /elsewhere`, because `/entry/direct` is inside `/entry`, and the walk
  then descends into what `direct` names. The chain is bounded at 32 hops. HDF5 itself
  traverses at most 16 links before it refuses to resolve one (`H5Pset_nlinks`), so twice
  that never decides for a member the library could open, while a file that manages to
  loop is named and skipped rather than walked for ever (#29's guarantee);
- a **hard link** is one of the object's own names, and that name is inside the group
  that holds it, so it needs no test. It is the one link that can still put a group that
  is an entity of the dataset inside another one, and object identity is the only way to
  see that: the entity groups and matched groups **of the file being read** are kept by
  `h5py` object id, and a link to one of them is named and skipped as before
  (`links into <path>, an entity group of this dataset; skipped`).

**What the rule leaves standing, said plainly.** Two cases are in rule and silent, and an
author reading a layout should know both:

- a **member of the params group itself** is read whatever it links to, a dataset in
  another entity's group or in a file the `pattern` does not match included. The author
  wrote that name in that group; `recursive` must not take away a column that the same
  YAML gives without it. Write the link out of the group if its target should not be read.
- a **hard link to a *subgroup* of a sibling entity group** is followed, and its values
  enter this entity's parameters and uid. `closed` holds the entity groups and the groups
  `entity_group` matched, not what is inside them, and no object-id set can hold that
  without walking every entity group of every file — the reason the name sets lost below.
  A hard link is genuinely a member of the group that holds it, so this stays in rule; the
  rule that would catch it (reference count > 1) lost for the reason in "the arguments
  that lost".

**The rule holds for every source tag.** `files` and `batch` read their params group in
the file, and a link out of that group — into another file of the dataset, or to a group
beside it — is skipped there too. Before this change only `groups` had any skip set.

**What is kept.** The ancestor guard of
[#29](https://github.com/slaclab/TileWright/issues/29) stays: a link *inside* the subtree
can still name a group already on the path being read (`/entry/sub/up -> /entry`), and
that walk would never end. The groups above each pending group are still carried, and
such a link is named and skipped.

**What is replaced.** The cross-file, lazily built skip set of ADR-0011's round 3
(`_ClosedGroups`, `_file_id`) is gone. A sibling entity group is not inside the subtree,
so no set is needed to keep recursion out of it; what remains is the per-file object-id
set for the hard-link case above, built once per file from the groups the walker already
lists.

**The way out for an author.** A group named under `params.group` or `params.groups` is
read wherever its path leads, a link into another file included. That path is the
author's explicit choice, as ADR-0011 records, and it is how a shared calibration group
is read (`{groups: {own: /, calibration: /calibration}}`), with or without `recursive`.

**netCDF bookkeeping.** `_Netcdf4Coordinates` and `_Netcdf4Dimid` join HDF5's
dimension-scale attributes (`CLASS`, `NAME`, `DIMENSION_LIST`, `REFERENCE_LIST`) in the
internal set, so they no longer reach labels or artifact metadata. netCDF-4 writes them
to tie a variable to its dimensions; they mean nothing outside the file that holds them,
and `_Netcdf4Coordinates` is an array in some variables and absent in others, which under
the Parquet guard of [#31](https://github.com/slaclab/TileWright/issues/31) turned a whole
`artifacts.parquet` column into JSON text (osti/1822259, where 4,384 artifact rows carry
it). Under `params: {from: attrs}` every attribute is still a parameter, the internal
names included, so no uid and no fingerprint changes.

## Why

Three rules were tried for #34, and each review found the leak one level below the group
the rule named. The fourth review (the iteration-11 skeptic of the campaign for
[#1](https://github.com/slaclab/TileWright/issues/1)) found three ways through at the
head of [PR #36](https://github.com/slaclab/TileWright/pull/36), all of them silent, all
of them in the uid:

1. **A soft link into a subgroup of a sibling entity group, in the same file.** With
   `entity_group: /runs` and `params: {group: /, recursive: true}`,
   `/runs/day/peek -> /runs/night/readout` gave the entity `day` the column `peek.gain`
   holding `night`'s value. The skip set held `/runs/night`, not its subgroups.
2. **The same link across files.** `station_a.h5:/runs/day/peek -> station_b.h5:
   /runs/night/readout`, where `station_b.h5` is another file of the dataset: its entity's
   value entered `day`'s parameters and uid.
3. **A `files` source has no skip set at all.** `run_0.h5:/entry/peer ->
   run_1.h5:/entry`, another entity of the same dataset, pulled that file's parameters
   into this entity's uid.

Every earlier rule named the groups recursion must not enter, and a name set cannot be
complete: knowing every group inside every entity group of every file means walking them
all. Turning the rule around — name what recursion *may* read, which is the subtree the
author pointed at — is a local test with nothing to enumerate, and it is the same test
for every source tag.

The fifth review (of round 2, at head `eb87eab`) found the pattern once more, one step
below the level the rule tested, and showed where the rule had to stop:

4. **A chain of links defeats the test.** `_outside` asked where *this* link points, not
   where that path itself leads, so with `/entry/direct -> /elsewhere` skipped,
   `/entry/hop -> /entry/direct` passed and `hop.gain` entered the uid with no message
   (reproduced with chains of 2 and 3 links, under `files`, `groups` and `batch`). The
   chain is now walked to its final target, bounded.
5. **A linked dataset below the group left the subtree.** The rule tested subgroups only,
   so `runs/day/sub/borrowed -> /runs/night/temperature` (a sibling entity's own value)
   and an external link to a file the `pattern` does not match both landed in `day`'s
   parameters and uid, on a path only recursion reaches. Recursion now holds for datasets
   too — but only below the group the author named, where the reader, not the author,
   chose to go.

The cost is borne by a layout that links a group, or a dataset below the params group,
from outside into an entity: it loses those columns and its uids change. None of the 25
datasets registered by this campaign is affected — no registered YAML sets
`recursive: true` — and PR #36 re-manifested every one of them in rounds 2 and 3 and
compared uids and `source_fingerprint` against the registered Parquet files.

## The arguments that lost

- **Name the groups recursion must not enter** (ADR-0011, rounds 1 to 3 of #21 and #34):
  the entity groups and matched groups of the file, then of every file of the dataset,
  compared by object id. It is enough for a link *to* one of those groups, and that is
  what the earlier reviews asked for. It lost because the set can never hold what lies
  *inside* those groups, which is leak 1 and leak 2 above, and because it says nothing for
  `files` and `batch`, which is leak 3.
- **Skip every link whose target file differs from the current one** (the brief for #34's
  first round, and the cross-file variant this PR shipped in round 1). It closes leaks 2
  and 3, and nothing else: a soft link inside one file still reaches another entity
  (leak 1). It also stops recursion at a link into a file the dataset's `pattern` does not
  match, a shared calibration file beside the data, which the subtree rule does too — but
  under a rule that draws the line at the file boundary rather than at the group the
  author named, so a link to a group beside the params group in the same file stays
  followed.
- **Follow a link out of the subtree** (today's behaviour before this change). A shared
  calibration group kept once and linked into every entity is sometimes exactly what an
  author wants, and the link is in the author's own file. It lost because such a link
  cannot be told apart from a link into another entity's data, and because naming the
  group under `params.groups` still reaches it, with the path visible in the YAML.
- **Skip a hard link to a group that has more than one name** (reference count > 1). It
  would close the hard-link case without an object-id set. It lost because it also drops a
  group an author deliberately gave two names inside the params group, which
  `TestParameterGroups::test_one_group_linked_twice_beside_the_path_is_read_under_both_names`
  pins with the uid `main` gives that file.
- **Leave linked datasets out of the rule everywhere** (the rule this ADR carried until
  the review of round 2). A soft or external link to a *dataset* was read wherever it
  pointed, at any depth. It lost below the params group: the review reached a sibling
  entity's own value (`runs/day/sub/borrowed -> /runs/night/temperature`) and a value in a
  file the `pattern` does not match, both silently, both in the uid, on a path only
  recursion reaches. What survives of it is the half above — a member of the group the
  author named — because a linked dataset there is one member the author wrote, with the
  name they chose (`test_links_are_resolved_by_the_library` pins it, external links
  included), because NeXus files name datasets across groups by link that way, and because
  the same YAML without `recursive` reads it.
- **Test the link's own target rather than the chain's end** (this PR's round 2). One test
  of `link.path` is cheaper and needs no bound. It lost to one extra hop: with
  `/entry/direct -> /elsewhere` skipped, `/entry/hop -> /entry/direct` passes the test,
  because `/entry/direct` is inside `/entry`, and the same group is skipped under one name
  and read under the other in one walk. It is the fourth appearance of the pattern this
  ADR describes — the leak comes back one step below the level the rule tests — and the
  bounded chain walk is what places the object instead of the first link.
- **Skip a hard link into a subgroup of a sibling entity group.** The residual case above.
  No name set can hold it (leaks 1 and 2 are the same argument), the reference-count rule
  that would catch it lost for its own reason, and `Group.name` cannot tell a hard link's
  second name from its first. It stays in rule, and it is recorded here and on the
  `source.groups.params` description rather than papered over.

## Consequences

- `ParamsSpec.recursive`'s description carries the rule, both halves, and
  `GroupsSource.params` states the corollary for a `groups` source (no sibling entity
  group and no matched group is read through a link, and the hard-link case that leaves
  standing) instead of the rule of ADR-0011. `docs/reference/dataset-yaml.md` is
  regenerated; no field is added, so `tests/test_contract.py::test_concept_budget` is
  unchanged.
- `reference/errors.md` gains the warning row for a link out of the subtree, beside the
  rows for the #29 ancestor link and the entity-group link.
- A dataset that reaches out of its params group's subtree by recursion loses those
  columns and changes uids. `register` refuses a changed `source_fingerprint` on an
  existing catalog key (ADR-0007), and a re-key is `tilewright delete` then `register`.
  The campaign's 25 registered datasets keep their uids and fingerprints, shown in the PR
  body's table; the only difference is `_Netcdf4Coordinates`, which leaves two datasets'
  artifact metadata (osti/1822259, zenodo/2539147) and hashes nothing.
- The warning fires once per link and per entity, so a `files` source whose thousand files
  each hold such a link prints a thousand lines. That is the shape of the existing
  unreadable-link warning, and it is what makes the skip visible in a log.
- `manifest.py` loses `_ClosedGroups` and `_file_id` and gains one function, `_outside`,
  which places a member's link chain; the object-id set is now three lines in the
  `groups` walker. `_outside` reads `get(..., getlink=True)` once per hop, so a member
  that is not a link costs one call and a chain of k links costs k; on a wide group that
  is one call per member, the same order as reading it.
- The subtree is compared by path. A params group reached *through* a soft link is read
  under the path the reader opened it with, so a soft link inside it that names its own
  target by an absolute path is outside that path and skipped, with the warning naming
  both. Naming the group under `params.groups` is the way to read it.
- Tests: `tests/test_manifest.py::TestRecursionStaysInTheSubtree` holds the five leaks and
  the positive cases — a soft link inside the subtree, absolute and relative, is read, and
  a link to the group being read is the #29 case; a chain out of the subtree is skipped
  under `files`, `groups` and `batch` (three links deep under `files`); a linked dataset
  below the group is skipped and named; a member of the group itself is read wherever its
  link leads; a soft link to an external link names that link's own file and path; and a
  hard link into a sibling entity group's subgroup is read, the residual case above;
  `TestNestedGroups::test_recursion_inside_an_entity_group_follows_no_link_out_of_the_group`
  covers the six link shapes inside one file, the hard link to another entity among them;
  `TestNestedGroups::test_recursion_takes_no_external_link_out_of_the_file` replaces the
  round-1 cross-file test and also shows the named-group way out.
  `TestArrayAttributes::test_hdf5_bookkeeping_attributes_are_still_left_out` covers the two
  netCDF names.
