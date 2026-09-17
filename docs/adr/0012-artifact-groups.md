# Artifact groups: one `artifacts` entry for every dataset in a group

**Status:** accepted, 2026-09-17. Extends ADR-0006 (two new keys in an `artifacts`
entry, a rule the `batch` tag refuses, and a rule for the characters of every `type`) and
ADR-0007 (a new fingerprint fact, hashed only when an entry has the new form). Decided in
the public comment on
[#12](https://github.com/slaclab/TileWright/issues/12#issuecomment-5712628229); the
character rule answers [#23](https://github.com/slaclab/TileWright/issues/23), and the
same change states what [#24](https://github.com/slaclab/TileWright/issues/24) asked.

## Decision

**Two ways to name an artifact.** An `artifacts` entry gives exactly one of `dataset` or
`group`; neither, or both, is a contract error.

- `dataset` is the entry as before: one array per entity.
- `group` names an HDF5 group (absolute under `files`, relative to each entity group
  under `groups`). The entry expands to one artifact per dataset *directly* in that
  group, in sorted name order. Subgroups are skipped; scalar (0-dim) datasets are
  included; a dataset with no dataspace (`h5py.Empty`) has no array to register and is
  skipped; a member that is a dangling link is skipped with a warning, as a dangling
  parameter is.
- `members` is an fnmatch pattern, matched case-sensitively (`fnmatchcase`) against each
  member's name, default `*`. It is allowed only with `group`: on a `dataset` entry it
  is a contract error.
- With `group`, `type` is a `str.format` template whose only placeholder is `{name}`,
  which must appear at least once and is replaced by the member's name
  (`type.format(name=<member>)`). Another placeholder (`{}`, `{0}`, `{run}`), a
  conversion or format spec (`{name!r}`, `{name:>6}`) and a lone brace are contract
  errors; a literal brace is written `{{` or `}}`. With `dataset`, a `type` that
  contains `{name}` is a contract error, and any other brace stays plain text, as before.

**Optional groups.** With `optional: true` an absent group is skipped for that entity.
Without it, an absent group is an error naming the file (for `groups`, `<file>:/<entity
group>`) and the group's full path. A present group in which no dataset matches
`members` is an error naming the group and the pattern, and listing the first names it
does hold, unless the entry is optional. A `group` that names a dataset is an error
either way.

**Unique types, per entity, after expansion.** The contract still refuses two `dataset`
entries (or a `dataset` entry and a `shared` entry) with one `type`. A `group` entry's
types exist only once the manifest has read the file, so `tilewright manifest` checks
them per entity: a type given twice, by two entries or by an entry and a shared axis, is
an error naming both (`artifacts[0] (type '{name}', group '/frames', member
'frame_0001') and artifacts[1] (dataset '/frames/frame_0001') both give the type
'frame_0001'`). An expanded type also reserves its locator names (`path_<type>`,
`dataset_<type>`, `index_<type>`) for that entity, so a parameter with such a name is
refused as for any other artifact.

**Where it is allowed.** Under `files` and `groups`. A `batch` source rejects the group
form with a contract error naming each such entry, because its first artifact sets the
batch size and every artifact's leading axis is the entity axis. A `shared` entry keeps
the `dataset` form only: `group` there is "not a contract key", and the `dataset`
description says so.

**Expansion at manifest time only.** `artifacts.parquet` holds one plain row per expanded
artifact (type filled in, the member's full HDF5 path in `dataset`), with no column that
records the entry. `register`, the adapter and `tilewright.client` are unchanged.

**The fingerprint hashes the spec.** When at least one entry has the group form,
`source_fingerprint` adds the fact `artifact_groups`: the sorted list of each such
entry's `[group, members]`, the group with any `/` at either end removed, because the
manifest reads `frames`, `/frames` and `/frames/` as the same group and an author who
edits one into another has not changed the data. An entry that names a `dataset` is not
hashed, as before (ADR-0007 never hashed artifacts), so no YAML without a group entry
changes: every golden fingerprint of the earlier ADRs still holds, and a test pins that a
`dataset` entry added to each example leaves its value alone. `optional` and the `type`
template are not hashed either; the order of the entries is not a fact. Tests pin three
fingerprints with a group entry (with and without `members`, under `files` and `groups`)
and that `optional`, the template, the order and the slashes around `group` leave them
alone.

**The characters of a type (#23).** A `type`, of an artifact or of a shared axis, is a
node key, and the Tiled client puts a key into a URL path as written. The contract now
refuses, naming the entry, a type that

- contains `/`, `?` or `#`;
- contains an ASCII control character (U+0000 to U+001F, U+007F);
- contains `%` followed by two hex digits (`%20`, `%2F`);
- is `.` or `..`.

For a `group` entry the check runs on the template with `{name}` filled in by `_`, so
only the template's own text can fail there, and `tilewright manifest` runs it again on
every expanded type, naming the member that made a bad one. Everything else is allowed,
because a local server served it back: dots anywhere (a locator key such as
`path_stage.x` is one flat key; registration nests only the entity's parameter columns),
`-`, `|`, a leading `_` or `.`, spaces (leading and trailing too), brackets, braces, `%`
without two hex digits, quotes and other punctuation, non-ASCII letters, combining marks,
no-break and zero-width spaces, C1 control characters. The `type` description states the
rule; the `shared` description points to it.

**A length limit, documented, not enforced.** With `--upload`, a server that keeps
arrays as files names a directory after the key, escaped with
`urllib.parse.quote_plus` (tiled 0.2.18, `adapters/zarr.py`, `init_storage`), and most
filesystems cap a name at 255 bytes: `x` × 256, `é` × 43 and `a+` × 64 fail at
registration there with `OSError: [Errno 36] File name too long`, reported as an
artifact error. Pointer registration serves all of them. The contract cannot tell the
transport, so the `type` description states the limit instead of refusing the type.

**Non-scalar parameter datasets (#24).** Under `files` and `groups`, a dataset in a params
group that is not a scalar (0-dim or of size 1) is skipped without a message, as
`manifest.py` has always done; the `from` description now says so, beside the `batch`
rule it already stated. No behaviour changes; tests pin it for a params group, a
`params.groups` entry and a `groups` source.

**Documented limit.** Each member becomes an array node of its own, registered with one
request and read back one step at a time. The `group` description says that thousands of
per-step datasets register slowly and are better stacked into one array, or into a
`batch` file, before onboarding. The measured registration rates, and a practical number
of artifacts per entity, belong to the publishing guide's registration step
([`docs/ONBOARDING.md`](../ONBOARDING.md), step 4), which the follow-up for #13 writes;
the contract and the explanation page carry no rate, and `explanation/sources.md` links
that step (its anchor, `#4-register-the-dataset`), so the follow-up only adds the
numbers.

## Why

A published file in the 32-dataset stress test (#1) keeps a daily series as one dataset
per day: five groups of 14,965 datasets each, in 9 files (osti/1872248, the ATS DayMet
forcing files). Each `artifacts` entry named one dataset, so full coverage needed 74,827
entries per entity and a 5.4 MB YAML, and the campaign registered the first 7 days of each
variable instead. One `group` entry per variable names them all.

**The character rule comes from a server, not from a guess.** A blind onboarding worker
renamed checkpoint fields such as `pressure.cell.0` and
`dupwind_relative_permeability|dpressure.face.0` (osti/2007951), and another renamed
netCDF variables such as `/_CLDHGH` (zenodo/1246857), because the surface did not say
which characters work. Every sample in `tests/test_node_keys.py` was registered into a
local `tiled serve` of the pinned Tiled (0.2.18), through both transports, and read back
by listing, by key, by path and from its locators. The ones that failed, and why:

| Sample | Pointer | Upload | Cause (tiled 0.2.18) |
|---|---|---|---|
| `a/b`, `/lead`, `trail/` | registers; read raises `KeyError` | artifact error | `client/container.py`, `Container.__getitem__`: `"/".join(keys).strip("/").split("/")` |
| `a?b`, `a#b` | registers; read raises `KeyError` | artifact error | same method: `self_link + "".join(f"/{key}" ...)` puts the key into the URL unescaped |
| `a%20b`, `a%2Fb`, `%41` | registers; read raises `KeyError` | artifact error | the server decodes the escape, so it looks up another key |
| `.`, `..` | registers; the read returns the entity, not the array | artifact error | a URL drops dot segments |
| `a\tb`, `a\nb`, `a\x01b`, `a\x7fb` (the characters, not the escapes) | registers; read raises `httpx.InvalidURL` | artifact error | httpx refuses a non-printable ASCII character in a URL |

So the rule forbids exactly those, and the integration test asserts that the server
serves back exactly the samples the rule accepts. A leading `_` was a worry in #23 and
works; a dot was a worry because dotted parameter columns are nested on registration,
and the locator keys are not.

**Expansion in the manifest** keeps the contract between the two commands as it is: the
Parquet manifest is plain rows, so `register` and both read paths need no change and no
new test surface.

**Why hash the spec and not its expansion.** `tilewright register` compares the
fingerprint of the YAML with the one stamped in the manifest before it connects, and it
never opens an HDF5 file, so the fingerprint has to be computable from the YAML alone:
the list of members is known only to the command that read the files. The spec is also
the stable statement: a file that gains a member does not describe other data. The group
and `members` are hashed because, like `pattern` and `entity_group`, they are a rule
that selects which parts of the files the dataset is; a changed rule under the same label
is refused as different data instead of registering a second set of arrays beside the
first. The `type` template is left out for the same reason a `dataset` entry's type
always was: renaming the node keys is not a change of data, and hashing it would make the
two forms disagree.

**The arguments that lost.**

- *A virtual "stack" artifact*, one array whose server-side adapter reads the members one
  by one (`{type: forcing, stack: /frames}` giving a `(N, ...)` array). It is the right
  data model for a time series: one node, sliced like any array, and registration costs
  one request. It lost because it needs a new adapter, a new manifest shape (a list of
  datasets per row), and new code on both read paths, and it has to decide what a
  member of another shape or dtype means. It is recorded as the follow-up.
- *A range form*, `{type: "t_{i}", dataset: "/frames/{i}", range: [0, 100]}`. It needs a
  second template language and cannot name members whose names are not numbers; the
  group form lists what the file holds.
- *Documentation only* (stack the datasets before onboarding). It stays as the advice for
  thousands of members, but a group of a few dozen arrays (channels, detector panels) is
  a normal file layout that a contract should be able to name.

## Consequences

- An author quotes the template, `type: "{name}"`: YAML reads an unquoted `{name}` as a
  mapping (a contract error, "must be a string"), and an unquoted brace inside a flow
  mapping as a syntax error. The `type` description says so.
- Some types that registered before (with a pointer, never readable) are now contract
  errors. Such a dataset served nothing for those arrays; renaming the type is the fix,
  and a `dataset` entry's type is not part of the fingerprint, so the rename registers
  under the same key once the old nodes are deleted.
- `tests/test_node_keys.py` holds the samples. Its integration tests start their own
  server (`pytest -m integration tests/test_node_keys.py`), so a Tiled upgrade can be
  checked against the rule in about a minute.
- The `--check` summary counts entries, not expanded artifacts: `artifacts=` there is the
  number of entries. The count after expansion is the one `tilewright manifest` prints.
- The artifact count formula gains a term: a group entry adds its matching members per
  entity (`reference/errors.md`, Expected counts).
- A string member is included like any scalar, and registration refuses a
  variable-length string with an artifact error (Tiled serves no `object` arrays; a
  local server refused one through both transports), as it always did for a `dataset`
  entry naming one. The `group` description tells the author to leave it out with
  `members`; skipping strings silently was not part of the decision.
- A member whose name gives a type that another entry also gives stops the manifest
  rather than dropping one; the fix is a prefix in the template (`dark_{name}`) or a
  narrower `members`.
- Changing a group entry's `type` template and registering again adds the renamed arrays
  beside the old ones, as renaming a `dataset` entry's type always did; the fix is
  delete, then register.
- The examples on the pages authors read (the field descriptions, `files.yml`,
  `explanation/sources.md`, the onboarding skill) are invented (`/frames/frame_0000`,
  `/channels/ch_a`); the dataset that motivated the change is named only here.
- `tests/test_contract.py::test_concept_budget` lists `group` and `members` among the
  keys of an `artifacts` entry, and pins the keys of a `shared` entry.
- The reference page, `explanation/sources.md` (the "why" for authors),
  `reference/errors.md`, `reference/manifest.md`, `explanation/identity.md`,
  `ONBOARDING.md`, the onboarding skill's Step 2 and `examples/datasets/files.yml`
  describe the form.
