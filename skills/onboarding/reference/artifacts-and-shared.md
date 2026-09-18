# Artifacts and shared axes

**Read this when** the source is chosen (Step 2): to decide which arrays each entity
serves, which arrays every entity shares, and what travels with them.

## Artifacts

One `artifacts` entry per array an entity exposes, with a `type` that becomes the array's
node key. Keep a dataset's own name where you can. A `type` may hold spaces, dots,
brackets and non-ASCII letters, but not `/`, `?`, `#`, an ASCII control character or `%`
with two hex digits, nor `.` or `..` alone: replace only those
([the full rule](dataset-yaml.md#artifacts)). Types must be unique across `artifacts` and
`shared`. `optional: true` marks an array that some entities lack.

### What travels with an array

Each array's own HDF5 attributes (`units`, `long_name`, ...) are captured automatically and
become the artifact's metadata; nothing to declare. An array attribute comes through as a
list, and [the manifest reference](manifest.md#artifactsparquet) says which values are
left out. Nothing interprets a value, and under `batch` an attribute describes the stacked
array, not the row ([what an attribute describes](manifest.md#what-an-attribute-describes)).

Two things do **not** travel, and nothing warns about either:

- **Attributes on a parent group.** Only the array's own attributes are captured. A record
  group that holds its components as datasets — openPMD's `fields/E` with `@gridSpacing`,
  `@gridGlobalOffset` and `@unitDimension` on the group, and `x`, `y`, `z` inside — gives
  its attributes to none of the component artifacts. When a reader needs them, read the
  group's attributes as entity parameters with `params.groups` and `from: attrs` (under
  openPMD's `groups` source, `{E: fields/E}`, relative to the entity group), or state them
  in `description` if they are the same everywhere.
- **Records that hold no array.** A group that stores a constant as attributes only
  (openPMD writes a species' `charge` and `mass` as a group with `@value` and `@shape`) has
  no dataset to serve, so it is simply absent. Read it as parameters the same way, or say
  in `description` that it is not served.

## Many arrays in one group

Some files keep a series as one dataset per step, or one per channel:
`/frames/frame_0000` to `/frames/frame_0099`. One `artifacts` entry names them all:

```yaml
artifacts:
  - {type: "{name}", group: /frames, members: "frame_*"}
```

`tilewright manifest` expands the entry into one artifact per dataset in the group whose
name matches `members`, `frame_0000` to `frame_0099`, and writes each to the manifest as
if it had an entry of its own, so registration and both read paths see nothing new.
`{name}` in `type` is the member's name, so `trace_{name}` over `/channels/ch_a` gives
`trace_ch_a`; quote the template. Subgroups are not members, `optional: true` skips an
entity without the group, and the types must stay unique after expansion. A `batch` source
does not take this form, because its first artifact sets the batch size, and neither does
`shared`. What counts as a member, and what an absent or empty group does, is in
[the `artifacts` fields](dataset-yaml.md#artifacts).

Each member is still an array of its own: one more node to register, and one read per
member to get a series back. A few dozen channels read side by side are fine.

### A series stored as pieces

Siblings with the same shape and dtype whose names are ordered (`day_001` … `day_365`,
`frame_0000` … `frame_0599`) are one array split up, whatever their number. A reader who
wants the series — one pixel over every day — makes one read per member: 600 members is
600 reads, even though 600 nodes register in seconds. Tell the owner what the usual read
costs at Step 4, below the registration thresholds too, and offer the choices in
[when the source's shape is the problem](counts-and-cost.md#when-the-sources-shape-is-the-problem).
Pieces of different shapes (ragged) cannot be stacked into one array: one artifact per
member is the right answer for them.

## Shared axes

Arrays *identical for every entity* go under `shared:`, if you serve them at all. The YAML
lists what the dataset serves, not what the file holds, so a constant placeholder nobody
would read is simply left out. An axis that varies per entity is an artifact, and an array
that is not an axis at all, a lookup or normalization table the whole dataset shares,
belongs in `shared:` too.

The entry names one copy by its absolute path, and `manifest` checks every copy the source
holds against it: under `files`/`batch` that path in each file, under `groups` the same
path inside **each entity group of each file**, so one file with four entity groups is
checked four times. A differing copy is refused, naming both — you do not have to digest
those arrays by hand first. The check is deliberately off in two shapes, and there you do:
a path **beside** the entity groups (a calibration group above them, say), and one inside
a group `exclude_groups` leaves out, are each one copy per file, so copies that differ
from entity group to entity group under such a path pass. A group that simply lacks the
array is passed over, and its entity is served the copy the entry names.

NeXus axes go to `shared:` only if identical across the files you sampled
([NeXus](nexus.md)); a netCDF dimension placeholder never does
([netCDF and CF](netcdf-cf.md#placeholders-and-length-1-coordinates)).

## Background

**Why expand a group entry in the manifest** rather than register one stacked array that
the server reads member by member: a stacked array is the better model for a series, but
it needs a new server adapter and new code on both read paths, while the expansion needs
neither.
