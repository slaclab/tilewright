# Nested entity groups: globs, `exclude_groups`, and `..` in a params path

**Status:** accepted, 2026-09-17. Extends ADR-0006 (a new key for the `groups` tag),
ADR-0007 (a new fingerprint fact, hashed only when it names a pattern) and ADR-0010
(location parameters keep nested entities distinct). Decided in the public comment on
[#11](https://github.com/slaclab/TileWright/issues/11#issuecomment-5712627796).

## Decision

**Globs in `entity_group`.** Each path segment of `GroupsSource.entity_group` may be an
fnmatch glob (`*`, `?`, `[...]`), matched case-sensitively (`fnmatchcase`) against the
names of the groups at that level; a segment without those characters is a plain name.
Only groups match. The matching groups are taken in sorted order, and the entities are the
subgroups of every one of them. `entity_group: "/*"` makes each `/<a>/<b>` group an
entity. There is no `**`.

**`exclude_groups`.** A new `groups` key: fnmatch patterns matched against the *name* of
each candidate subgroup, not its path, so an entry may not be empty or contain `/` (a
contract error). Excluded groups are not entities and are not counted as siblings. The
key also applies when `entity_group` is omitted (the file's top-level groups).

**`..` in a params group path.** Under `groups`, a `params.group` or `params.groups` path
may start with `..` segments. They leave the entity group and resolve against its path:
`..` is the group that holds the entity group and its siblings, `../calibration` a group
beside them, `../..` one level higher. `..` anywhere but at the start is a contract error
for every tag. Under `files` and `batch` a path starting with `..` is a contract error,
since there is no entity group to leave. A path that climbs above the file root is a data
error naming the entity (`<file>:/<group>`) and saying how many `..` to remove; climbing
exactly to the root reads the root. `exclude` paths are written in the same frame
(`../calibration/notes`).

**Sibling arrays.** A group reached through `..` is read by the batch rule, with N the
number of sibling entity groups: the subgroups of the same matching group, after
`exclude_groups`.

- A 1-D dataset of length N gives one value per entity: element *i* goes to the *i*-th
  sibling, with the names sorted as text. `scan_01` … `scan_12` pair with elements 0 …
  11; `scan_1` … `scan_12` do not, since `scan_10` sorts before `scan_2`. The field
  description warns about it.
- A scalar (0-dim or size 1) is given to every sibling.
- Anything else, a 1-D dataset of another length included, is skipped without a message,
  as in `batch`.
- Under `from: attrs` the group's attributes are given to every sibling; an array
  attribute is not split.
- The group a path names is read as written, whatever it is: an excluded group, a group
  of another set (`../../south/calibration`), or an entity group (`../det_a`). It is
  read by the rule of every group reached through `..`: its scalars go to every sibling,
  and its 1-D datasets of length N are split among them, so under `../det_a` the
  detector `det_b` takes element 1 of `det_a`'s per-detector array.
- Such a group is read once per sibling set, not once per entity.

**No recursion from a `..` group.** A `groups` params block with `recursive: true` may
hold no path that starts with `..`: a contract error that names the path, with the line
`Fix: name each group you need under params.groups, without recursive`. `recursive` is
one flag for the whole block (`ParamsSpec.recursive`), so recursion inside the entity
group and a `..` group cannot be combined in one block either: the author names the
entity group's subgroups too (`{own: /, readout: readout, calibration: ../calibration}`).
Under `files` and `batch` the error for `..` itself comes first.

**Recursion inside the entity group** stays. It never goes into an entity group or a
matching group of the file, of any sibling set. A group is known by the HDF5 object it
is (`h5py` object ids), not by the path it was opened through, so a soft link or a
second hard link inside an entity group does not lead the reader into another entity,
into another set's matching group, or back into its own entity group or matching
group. A link to a group *inside* one of them (another detector's subgroup, another
site's `calibration`) is still followed: knowing every such group would mean walking the
subtree of every matching group. Only the scalars of such a group are read, since a path
inside the entity group splits no array, so nothing is paired by another set's names.

**Different parameter sets.** Entities whose groups hold different parameters get null
for the ones they lack. This is how `entities.parquet` always behaved, and it is now
written down once, in `docs/explanation/data-model.md`, with its one side effect: a
column of integers that has a null is written as floats (the uid is computed before, from
the int).

**The fingerprint.** `exclude_groups` is a fact only when it names a pattern, and then as
a sorted set, since the order of the patterns changes no uid. `source_fingerprint` builds
its facts by hand, so the empty default adds nothing and no existing YAML is
re-fingerprinted. `entity_group` was already hashed; a glob is a string like any other.
Tests pin the empty case at the `b268731` value, a glob `entity_group` (the same value at
`b268731`), two `exclude_groups` values and a nested variant.

**Also in this change** (contract-surface fixes found since ADR-0010):

- a `params.location` group whose name starts with `_` is a contract error. The review of
  [#20](https://github.com/slaclab/TileWright/pull/20) found that `(?P<_provenance>...)`
  was hashed into the uid, then dropped from `entities.parquet` with the manifest's own
  bookkeeping column; the collision report also hides such names;
- `DatasetMetadata.data_type` lists all four vocabulary ids (`optimization` was missing);
  a test keeps the list equal to `vocabulary.yml`;
- `ParamsSpec.group` says that under `groups`, `/` is the entity group, not the file root.

## Why

Two published layouts in the 32-dataset stress test (#1) registered at the wrong
granularity or with nothing to query:

- **osti/1972213**: the natural entity is `/<design>/<fluid>`, two group levels deep, and
  the design's parameters sit in the sibling group `/<design>/fixed_params`; the two
  designs have different parameter sets (9 and 6). Written as
  ```yaml
  entity_group: "/*"
  exclude_groups: [fixed_params]
  params:
    groups: {design: ../fixed_params}
    location: '/(?P<design_name>[^/]+)/(?P<fluid>[^/]+)$'
  ```
  it gives 4 entities instead of 2. The two fluids of one design read the same
  `fixed_params`, so under `identity: params` only the location parameters keep them
  apart: `params.location` (ADR-0010) captures the group names for exactly this.
- **zenodo/3528199**: 11 load steps `step_01` … `step_11` under
  `/DataContainers/RawDataContainer_T`, with `Load (11,)` and `Displacement (11,)` stored
  beside the step groups. `params: {group: ..}` gives each step `Load[i]` and
  `Displacement[i]`; before, the steps registered with `params: null`.

`..` reuses a notation every author knows, and the sibling rule reuses the batch rule, so
the reader gains no new reading mode: a group beside the entities is a small batch file
whose rows are the siblings.

**Why recursion from a `..` group is refused.** The decision does not mention
`recursive`, and neither of its layouts sets it. Three reviews of
[#21](https://github.com/slaclab/TileWright/pull/21) each found one more way for
recursion from a `..` group to read another sibling set's values into an entity, and so
into its uid, which cannot change once the entity is registered:

1. *Round 1* (review 5236326435): the reader skipped only this set's siblings, so `../..`
   under `"/*"` read the detector groups of the other sites into every entity.
2. *Round 2* (review 5236686072): the reader skipped every entity group of the file, but
   `../..` still read the other sites' `calibration` groups and split their 1-D arrays
   by *this* site's N. An array in `/south/calibration` is ordered by south's detector
   names, yet its element *i* went to north's *i*-th detector whenever the two sites had
   as many detectors.
3. *Round 3* (review 5237492552): the reader entered no matching group, but under
   `"/run_*/scans"` a path above the point where two runs branch (`../../..`) still read
   `/run_2/scan_energy`, beside run 2's matching group, and split it among run 1's scans.

Each fix drew the boundary one level higher, and the next review found the case above
it. The decision pairs an element with an entity "by position among the sibling group
names", and only the author knows which group beside or above the entities holds values
in that order; recursion cannot know it. Naming each group can. Inside the entity group
no other entity is reached except through a link, and the object-id rule above closes
that.

**The arguments that lost.**

- *An absolute params path* (`params: {group: /fixed_params}` resolved from the file
  root). It is simpler to write and to explain. It lost because it cannot vary per entity:
  in osti/1972213 each design has its own `fixed_params`, and an absolute path names one.
- *`entity_depth: N`* (entities are the groups N levels down). It is simpler than a glob.
  It lost because it cannot skip `fixed_params`, which sits at the entity level beside the
  fluids, and it cannot pick some top-level groups and not others.
- *An error for a 1-D dataset of another length* in a `..` group. It would catch a
  miscount. It lost because a group beside the entities often holds arrays that are not
  per-entity (an axis, a lookup table), and `batch` already skips them; one rule for both.
- *Numeric ("natural") sorting of sibling names.* It would pair `step_1` … `step_10`
  correctly. It lost because it has to guess where a number starts in a name
  (`run2_scan10`), text order is what `h5py` and every file browser show, and the entity
  order is the same text order everywhere else. The description warns instead.
- *Recursion from a `..` group with a boundary.* It saves the author from naming each
  group of a deep calibration tree. Each boundary below was tried or proposed on #21 and
  lost to the refusal, because the next review found values it let through:
  - *Skip every entity group of the file* (round 2). It still read the other sets'
    excluded groups and split their arrays by this set's N (finding 2).
  - *Also skip every matching group* (round 3). One boundary for every set, and it
    closed finding 2, but it still read a branch above the matching groups that leads to
    another set's matching group, and the arrays beside it (finding 3).
  - *Also skip every group that holds a matching group* (the suggestion of review 3). It
    closes finding 3, but it also stops `..` of a single-match pattern (`/entry/data`)
    from reading `/entry`, where nothing can be mispaired; its refinement (skip the
    groups that hold some matching groups but not all) is one more rule to explain, for
    a use the decision never asked for.
  - *Recurse into this set's own matching group only* (the suggestion of review 2). The
    columns would differ per set for one kind of value (`top.north.calibration.offset`
    on north, `top.south...` on south, each null on the other), while
    `../calibration` gives every set the same column.

  The refusal costs an author with a deep tree beside the entities one `groups` entry
  per group. Nobody asked for recursion there, and three rounds showed that it cannot be
  made safe cheaply.

## Consequences

- A YAML without the new keys validates, reads and fingerprints as before. The golden
  fingerprint tests pass unchanged.
- Under `identity: params`, entities in different matching groups that read the same
  values collide. The collision report says so; `params.location` capturing the group
  names is the fix, and the example in `examples/datasets/groups.yml` shows it.
- A file where `entity_group` matches no group is an error naming the file and the
  pattern (`entity_group '/x/*' matches no group`); the old message for a missing plain
  path (`not found`) is gone. A file where the matching groups have no subgroup left is an
  error that mentions `exclude_groups` when it is set. A matching group with no subgroup
  contributes no entity and is not an error while another one has some.
- The sibling pairing is by sorted name. Unpadded numbers pair in text order, silently;
  the field description, the explanation page and a test document it.
- The field-description warning uses `scan_1`/`scan_10`, not `step_1`/`step_10` as the
  decision comment wrote it: the pages authors read carry invented examples only, and
  `step_XX` is the layout of zenodo/3528199. For the same reason the example YAML and the
  explanation page use `/<site>/<detector>` beside `calibration`, and `scan_01` …
  `scan_12` beside `beam_current`.
- Two rules go beyond the decision text without contradicting it:
  - *A size-1 dataset is broadcast like a 0-dim one.* The decision names 0-dim values
    only. The contract already calls a size-1 dataset a scalar (NeXus writes scalars
    with shape `(1,)`), and `batch` broadcasts both; one reading of "scalar" for both
    rules keeps the sibling rule the batch rule.
  - *`..` may only lead a path, for every tag.* The decision speaks of `..` at the start
    only. HDF5 has no `..` link, so `run/../calibration` would look for a group named
    `..`, find none and read nothing without a message; a contract error says so
    before any file is opened.
- The two recursion rules go beyond the decision too, which does not mention
  `recursive`:
  - *No recursion from a `..` group* (the Why section has the three findings behind it).
    The decision's two layouts read the same as before, since neither sets
    `recursive`: osti/1972213 names its excluded group (`../fixed_params`), and
    zenodo/3528199 reads `..` itself. Tests turn every YAML that recursed from `..` in
    the earlier rounds, and the case of the third review, into contract errors; two of
    them also check that the Fix line's YAML gives each entity its own set's values.
  - *Recursion inside an entity group follows no link to an entity group or a matching
    group.* On `main` before this change, such a walk followed every link. A link to a
    sibling entity group read that entity's values under the link's name, and now it
    reads nothing; the uids of an already registered `groups` dataset with
    `recursive: true` and such a link change. A link back to the entity's own group, or
    to the group that holds it, made that walk run until it was killed, so no dataset
    with one was ever manifested with `recursive: true`. A link cycle that passes
    through no entity group or matching group still does not end; that is
    [#29](https://github.com/slaclab/TileWright/issues/29), for `files` and `batch` too.
- The group a path names is not checked. The path is the author's explicit choice, and
  knowing that it names an entity group or a group of another set needs the file, so it
  could not be a contract error. The sharp edge is written down here:
  `../../south/calibration` reads south's `calibration` for north's detectors, split by
  north's N. The third review of #21 suggested a warning for it: the manifest could tell
  that a named `..` group is, or lies inside, another set's matching group. It is not
  added: without recursion, only a path that names the other set reaches it, and the
  field description says that the group a path names is read whatever it is. A test
  pins how `../det_a` is read, so the choice cannot change unnoticed.
- `tests/test_contract.py::test_concept_budget` lists `exclude_groups` among the keys of
  `groups`.
- The reference page, `examples/datasets/groups.yml` (commented alternatives that
  `tests/test_examples.py` builds and runs), the onboarding skill's Step 2,
  `explanation/sources.md`, `explanation/data-model.md` and `errors.md` describe the
  change.
