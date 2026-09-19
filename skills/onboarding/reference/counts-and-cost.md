# Counts and cost

**Read this when** you predict the counts (Step 3), when the data is a series stored as
pieces or an acquisition split across files, and before registering a large dataset: how
many entities and artifacts the manifest will report, how long registering them takes, and
what to offer when the source's shape is the problem.

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

## When the source's shape is the problem

Some sources are cheap to describe and expensive to use. Two costs, either one enough:

- **Registering.** A file that keeps each day, step or channel as a dataset of its own
  gives one entity thousands of artifacts. One such dataset held 74,827 artifacts per
  entity and took about 21 hours to register. Raise it when the nodes you predict
  (entities × artifacts per entity) pass about 10,000, or one entity carries more than
  about 1,000 artifacts.
- **Reading.** A series stored as pieces
  ([artifacts and shared axes](artifacts-and-shared.md#a-series-stored-as-pieces)), or an
  acquisition split across files
  ([source and entity](source-and-entity.md#choosing-between-them)), registers quickly and
  makes the usual read one request per piece. Raise it whatever the count.

This is the owner's decision, made **before sign-off**, not discovered at `register` or by
the first reader. Give them the node count and a rough time at a few tens of nodes a
second, what the usual read costs, and the choices:

- **Register as it is**, stating both costs. The run resumes if it is interrupted.
- **Register a subset**: fewer members with `members`, fewer files with `pattern`, or a
  trial with `register -n`. `members` is one fnmatch pattern, not a numeric range: over unpadded names
  `[0-9]` picks 0–9 and `1[0-9]` picks 10–19, and no single pattern picks exactly 0–19.
  Choose a range one pattern can express (the first ten, the tens), or write one entry
  per pattern. Say in `description` what was left out.
- **Register a converted copy**, made by the producer, or by the owner when there is no
  producer to ask (a published record) and they can keep the copy beside the data. Two
  recipes, each a short h5py script the owner runs and keeps with the copy:
  - **Stack** the pieces into one chunked array, `(steps, ny, nx)`, or into a `batch`
    file. A real copy: it costs disk, and it stays correct if the originals move.
  - **A virtual dataset (VDS)**, which maps the pieces into one array without copying.
    Every read resolves the source files at read time, and a source that is missing or
    unreachable from the server's view reads as the fill value, **with no error**. Set the
    fill value to NaN for floats, keep the source paths valid as the server sees them, and
    make the read-back compare the first, the last and a few other members with the
    originals.

  Either way the copy registers as ordinary data; say in `description` what it was made
  from.

TileWright builds no converted copies for you. Whichever the owner picks, record it in a
comment above `artifacts:`.
