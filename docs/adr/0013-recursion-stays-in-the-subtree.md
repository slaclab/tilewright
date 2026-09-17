# Recursion stays inside the params group's own subtree

**Status:** accepted, 2026-09-17. Narrows ADR-0011's recursion rule (recursion never
enters an entity group or a matched group) and settles
[#34](https://github.com/slaclab/TileWright/issues/34) after three rounds of review;
keeps ADR-0007's identity rule (only what is read is hashed) and ADR-0011's refusal of
`recursive` together with a `..` path. Decided by the fix campaign's orchestrator after
the fourth review of the rule, on the three leaks below.

## Decision

**`params.recursive` follows only what lies inside the subtree of the group it reads.**
While recursing, a member reached through an HDF5 link whose target is not inside that
group is named in a WARNING and skipped:

```
  WARNING: /data/station_a.h5:/runs/day/peek links to /data/station_a.h5:/runs/night/readout, outside the group being read (/runs/day); skipped
```

The target is placed from the link, not from the path the reader opened it through
(`h5py` reports the opened path for a linked object, so `Group.name` cannot say where a
link led):

- an **external link** resolves in another file, so it is never inside the subtree;
- a **soft link**'s target path, resolved against the group that holds the link when it
  is relative, must be the group the walk started from or one under it, in that file;
- a **hard link** is one of the object's own names, and that name is inside the group
  that holds it, so it needs no test. It is the one link that can still put a group that
  is an entity of the dataset inside another one, and object identity is the only way to
  see that: the entity groups and matched groups **of the file being read** are kept by
  `h5py` object id, and a link to one of them is named and skipped as before
  (`links into <path>, an entity group of this dataset; skipped`).

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

The cost is borne by a layout that links a group from outside into an entity: it loses
those columns and its uids change. None of the 25 datasets registered by this campaign
is affected; PR #36's round 2 re-manifested every one of them with this rule and compared
uids and `source_fingerprint` against the registered Parquet files.

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
- **Apply the rule to linked datasets too.** A soft link to a *dataset* elsewhere in the
  file is still read, as it always was (`test_links_are_resolved_by_the_library` pins it,
  external links included). It lost because a linked dataset is one member the author
  named in the params group, with the name they chose, while a linked group is an open
  door; and because NeXus files name datasets across groups by link so often that the
  broader rule would drop parameters, and change uids, on files nobody complained about.

## Consequences

- `ParamsSpec.recursive`'s description carries the rule, one sentence, and
  `GroupsSource.params` states the corollary for a `groups` source (no sibling entity
  group and no matched group is read through a link) instead of the rule of ADR-0011.
  `docs/reference/dataset-yaml.md` is regenerated; no field is added, so
  `tests/test_contract.py::test_concept_budget` is unchanged.
- `reference/errors.md` gains the warning row for a link out of the subtree, beside the
  rows for the #29 ancestor link and the entity-group link.
- A dataset whose params group links out of its subtree loses those columns and changes
  uids. `register` refuses a changed `source_fingerprint` on an existing catalog key
  (ADR-0007), and a re-key is `tilewright delete` then `register`. The campaign's 25
  registered datasets keep their uids and fingerprints, shown in the PR body's table; the
  only difference is `_Netcdf4Coordinates`, which leaves two datasets' artifact metadata
  (osti/1822259, zenodo/2539147) and hashes nothing.
- The warning fires once per link and per entity, so a `files` source whose thousand files
  each hold such a link prints a thousand lines. That is the shape of the existing
  unreadable-link warning, and it is what makes the skip visible in a log.
- `manifest.py` loses `_ClosedGroups` and `_file_id` and gains one function, `_outside`,
  which places a member's link target; the object-id set is now three lines in the
  `groups` walker.
- The subtree is compared by path. A params group reached *through* a soft link is read
  under the path the reader opened it with, so a soft link inside it that names its own
  target by an absolute path is outside that path and skipped, with the warning naming
  both. Naming the group under `params.groups` is the way to read it.
- Tests: `tests/test_manifest.py::TestRecursionStaysInTheSubtree` holds the three leaks and
  the positive case (a soft link inside the subtree, absolute and relative, is read; a link
  to the group being read is the #29 case);
  `TestNestedGroups::test_recursion_inside_an_entity_group_follows_no_link_out_of_the_group`
  covers the six link shapes inside one file, the hard link to another entity among them;
  `TestNestedGroups::test_recursion_takes_no_external_link_out_of_the_file` replaces the
  round-1 cross-file test and also shows the named-group way out.
  `TestArrayAttributes::test_hdf5_bookkeeping_attributes_are_still_left_out` covers the two
  netCDF names.
</content>
