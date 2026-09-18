# Counts and cost

**Read this when** you predict the counts (Step 3), and before registering a large
dataset: how many entities and artifacts the manifest will report, and how long
registering them takes.

## Expected counts

| Source | Entities | Artifacts |
|---|---|---|
| `files` | files matched by `pattern` (`ls <directory>/<pattern> \| wc -l`) | entities × non-optional `artifacts` entries, plus optional ones where present |
| `batch` | sum over files of the leading axis of `artifacts[0]` | entities × `artifacts` entries |
| `groups` | subgroups of every group `entity_group` matches (or of the root), less those `exclude_groups` names, summed over files | entities × `artifacts` entries |
| `table` | rows of the table | 0 |

Plus one artifact row per `shared` axis, reported separately as `shared=S`. A `group` entry
counts, for each entity, the datasets directly in its group whose names match `members`
(none where an optional group is absent). `tilewright manifest --check` prints the number
of entries, not this count.

Say how you got each number ("5 files × `/spectra` leading axis 2000 = 10,000 entities; 1
artifact each + 2 shared axes"). A mismatch with what `manifest` reports means the data
was misread ([what usually causes it](troubleshooting.md#tilewright-manifest-the-data)).

## How long registering takes

Cheap is not instant. For a pointer registration every entity container and every
artifact is one HTTP round trip, so the time follows the number of *nodes* —
entities × artifacts, plus one per shared axis — and not the bytes on disk. A few tens of
nodes a second is the order of magnitude for a server on a SQLite catalog, which makes ten
thousand entities minutes and a hundred thousand hours. Measure your own rate rather than
trusting that: time `tilewright register -n 100`, divide, and multiply out. Two levers if
it matters: `--max-workers N`, which helps a dataset of many entities and hardly one of
few entities and very many arrays ([the flags](https://github.com/slaclab/tilewright/blob/main/docs/reference/cli.md#tilewright-register) say
why), and the run's own resumability — a long one can simply be started again. Reading
back is not affected: a query answers from the catalog database, at any size.

An upload moves the real data, so its wall-clock scales with size and uplink, not node
count.

## When the source's shape makes registration slow

Some sources are cheap to describe and expensive to register: a file that keeps each day,
step or channel as a dataset of its own, so that one entity carries thousands of
artifacts. One such dataset held 74,827 artifacts per entity and took about 21 hours to
register. That is a decision for the owner, and it has to be made **before sign-off**, not
discovered at `register`.

Raise it when the nodes you predict (entities × artifacts per entity) pass about 10,000, or
one entity carries more than about 1,000 artifacts. Give the owner the node count, a rough
time at a few tens of nodes a second, and the choices:

- **Register everything**, stating the time. The run resumes if it is interrupted.
- **Register a subset**: fewer members with `members`, fewer files with `pattern`, or a
  trial with `register -n`. Say in `description` what was left out.
- **Ask the producer to convert**: stack the per-step datasets into one array, a
  `(steps, ny, nx)` dataset, or into a `batch` file, so the series becomes one artifact
  that slices like any other.

TileWright builds no derived files for you. Whichever the owner picks, record it in a
comment above `artifacts:`.
