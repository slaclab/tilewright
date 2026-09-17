# Errors and warnings

Every message `tilewright` and the server produce that has a specific cause, in the order
of the pipeline that raises it. [How to publish a dataset](../ONBOARDING.md) has a short
table of the common ones; this page is the full set.

---

## `tilewright manifest`: the contract

Every contract problem is reported at once, one line each, then exit `1`.

| Message | Cause | Fix |
|---|---|---|
| `contract error: the contract changed: 'data' and 'parameters' are now one 'source' block` | A YAML in the old `data:`/`parameters:` shape | The [migration table](dataset-yaml.md#migration-from-the-data-parameters-contract) |
| `contract error: <field> is required` | A required field is missing or empty | Add it; an empty string counts as missing |
| `contract error: <field> is not a contract key` | A typo or an unknown key in a closed section | Fix the name; only `metadata` accepts arbitrary keys |
| `contract error: source: exactly one of files \| batch \| groups \| table is required` | No tag, or two | Keep one |
| `contract error: source.<tag>.directory must be an absolute path` | A relative directory | Write the full path (`pwd -P`) |
| `contract error: source.<tag>.params: 'group' and 'groups' are mutually exclusive` | Both given | Keep one; to nest a single group, name it under `groups` |
| `contract error: source.files: params.group '<path>' starts with '..', which leaves an entity group, and only a 'groups' source has one` (or `source.batch`, `params.groups.<name>`) | A `files` or `batch` params path starts with `..`. Only a `groups` source has an entity group to leave | Write the path inside the file, from its root: `/calibration` |
| `contract error: source.groups: params.group '<path>' starts with '..', and 'recursive: true' is for paths inside the entity group only` (or `params.groups.<name>`), then a `Fix:` line | A `groups` params block sets `recursive: true` and holds a path that starts with `..`. `recursive` applies to every path of the block, and from a group outside the entity group it would reach the groups of other entities | Follow the `Fix:` line: remove `recursive` and name each group you need under `params.groups`, the entity group's own subgroups included: `{site: .., calibration: ../calibration, own: /, readout: readout}` |
| `contract error: source.<tag>.params: group '<path>': '..' may only lead the path` (or `groups.<name>`) | A `..` after a name, as in `run/../calibration` | Drop it, or start the path with the `..` segments: `../calibration` |
| `contract error: source.groups.exclude_groups: '<entry>': each entry is a pattern matched against the name of a subgroup` | An empty entry, or one with a `/` | Write the subgroup's name, or a glob of it: `calibration`, `cal*`. It is matched against names, never paths |
| `contract error: key '<K>' does not match slug(label)` | `label` changed after the key was written | Restore the label, or delete the `key:` line and rerun. A drifted key is never silently rewritten, because the old key may already hold registered data |
| `contract error: a 'table' source has no readable arrays: remove 'artifacts'` | `artifacts` on a table source | Remove it |
| `contract error: source.table.identity is not a contract key` | `identity` under a table. A table's identity is its `id` column(s) ([identity and keys](../explanation/identity.md)) | Remove it. To tell rows with a repeated id apart, list more columns in `id` |
| `contract error: source.table.id: must be a column name or a list of column names, none of them empty` (or `names a column more than once`) | `id` is empty, not a string, or a list with an empty, non-string or repeated entry | Write one column, `id: run`, or several, `id: [specimen, replicate]` |
| `contract error: source.<tag>.params.location: is not a Python regular expression (...)` | `location` does not compile; the parentheses hold Python's own words, such as `missing ), unterminated subpattern` | Correct the expression. Write it in single quotes, where YAML keeps every backslash: in double quotes `"\d"` is a YAML error and `"\b"` becomes a backspace ([parameters from the location](../explanation/sources.md#parameters-from-the-location)) |
| `contract error: source.<tag>.params.location: has no named group, so it gives no parameter` | `location` has only unnamed groups, `(...)`, or none; unnamed groups are wildcards | Name each value you want: `(?P<year>\d{4})` |
| `contract error: source.<tag>.params.location: may not name a group uid` (or `source_group`) | A named group is called like a column of `entities.parquet` that is not a parameter | Choose another name |
| `contract error: source.<tag>.params.location: may not name a group _<name>: a name that starts with '_' is kept for the manifest's own use` | A named group starts with `_`. The manifest keeps its own bookkeeping under such names and leaves it out of `entities.parquet` | Choose a name that starts with a letter |
| `contract error: artifact types must be unique` | Two artifacts or shared axes share a `type` | Rename one; types become node keys |
| `contract error: artifacts[<i>]: give exactly one of 'dataset' (one array) or 'group' (one array per dataset in that group)` | An `artifacts` entry with neither, or with both | Keep one ([the `artifacts` fields](dataset-yaml.md#artifacts)) |
| `contract error: artifacts[<i>]: 'members' picks the datasets of a 'group'` | `members` on an entry that names a `dataset` | Remove it, or name a `group` |
| `contract error: artifacts[<i>]: type '<t>' has no '{name}'` (or `holds '{name}', which only a 'group' entry fills in`) | A `group` entry whose `type` lacks `{name}`, or a `dataset` entry whose `type` has it | Put `{name}` in a group entry's type, `'trace_{name}'`, in quotes; write a dataset entry's type out |
| `contract error: artifacts[<i>]: type '<t>' holds {...}; '{name}' is the only placeholder` (or `is not a template (...)`) | A `group` entry's `type` with another placeholder, a format such as `{name:>6}`, or a lone brace | Keep `{name}` alone; write a literal brace as `{{` or `}}` |
| `contract error: artifacts[<i>].type must be a string` | An unquoted template, `type: {name}`, which YAML reads as a mapping | Quote it: `type: "{name}"` |
| `contract error: artifacts[<i>]: a 'batch' source takes 'dataset' entries only` | A `group` entry under `batch`, whose first artifact sets the batch size | Name each array of the group in an entry of its own |
| `contract error: shared[<i>].group is not a contract key` | A `group` under `shared` | A shared entry names one array, with `dataset` |
| `contract error: artifacts[<i>]: type '<t>' contains '/', which separates the keys of a path; a type is a node key that travels in a URL, so the server would not serve that array back` (or `shared[<i>]`; or `'?'`, `'#'`, an ASCII control character, `'%20'` and the like, or `is a dot segment`) | A `type` the server would register but never serve back, or refuse | Replace the character, with `_` say. Spaces, dots, brackets, `-`, `\|`, a leading `_` or `.`, and non-ASCII letters are fine ([the `type` field](dataset-yaml.md#artifacts)) |
| `note: metadata.<field> '<v>' is not in the vocabulary` | A facet value with no canonical id | Non-fatal by design ([the soft vocabulary](../explanation/vocabulary.md)). Prefer an id so the dataset lands on the same facet as everyone else's |

## `tilewright manifest`: the data

| Message | Cause | Fix |
|---|---|---|
| `no files match '<pattern>' under <directory>` | Wrong directory or pattern | `ls` the directory; the default pattern is `**/*.h5`, and the glob rules are in [the `pattern` field](dataset-yaml.md#sourcefiles) |
| `OSError: Unable to open file ... file signature not found` | The pattern matched a non-HDF5 sibling: a NetCDF twin, a Parquet sidecar, a `.gz` | Tighten `pattern` |
| `<file>: artifact type=... dataset '...' not found (mark it 'optional: true' if some entities lack it)` | Wrong HDF5 path, or an array that only some entities have; in `groups`, an absolute path where a group-relative one is expected | Dump one file (`h5py.File(p).visititems(print)`) and correct `dataset`, or add `optional: true` |
| `<file>: artifact type='<t>' group '<g>' not found (mark it 'optional: true' if some entities lack it)` (the entity is named `<file>:/<group>` for `groups`) | The `group` of an entry names nothing in that file. Under `groups` it is relative to each entity group, and the message shows the full path | List the file's groups (`h5py.File(p).visit(print)`) and correct `group`, or add `optional: true` |
| `<file>: artifact type='<t>' group '<g>' is a dataset: name it with 'dataset'` | The `group` of an entry names a dataset | Write it as a `dataset` entry, with a `type` without `{name}` |
| `<file>: artifact type='<t>' group '<g>' has no dataset whose name matches members '<m>'; it holds N datasets (...)` | No dataset directly in the group matches `members` (case matters), or the group holds only subgroups, which are never members | Compare `members` with the names the message lists and correct it or `group`, or add `optional: true` if only some entities have them |
| `<file>: artifacts[<i>] (...) and artifacts[<j>] (...) both give the type '<t>'` (or `shared[<k>] (...) and ...`) | Once the `group` entries are expanded, two entries, or an entry and a shared axis, give one entity the same `type` | Change a `type`, for example a prefix in the template (`dark_{name}`), or narrow `members` |
| `<file>: artifact type='<t>' group '<g>': the member '<n>' gives the type '<type>', and that type contains ...` | A member's name, put into the `type` template, makes a type the server would not serve back (see the contract row above) | Leave the member out with `members`, or rename the dataset in the file |
| `WARNING: <file>: <group>/<name> unreadable (...); skipped` | A member of a `group` entry is a link that leads nowhere | The other members are registered. Repair the link in the file if you want that array |
| `WARNING: <file>:<group>/<name> links to <file>:<path>, outside the group being read (<group>); skipped` | With `recursive: true`, a member the descent reads -- a subgroup of the params group, or anything below that group -- is an HDF5 link out of it, or the last link of a chain is, or its target path is spelled inside the group and runs through a link that is not: a soft link elsewhere in the file, or an external link, which resolves in another file. The descent follows only what lies inside the group, subgroups and datasets alike; it decides on the object each name resolves to, not on the text of its path, and `<path>` is where the walk leaves the group (the file alone, with no path, when only the file the object really lives in is known) ([the `recursive` field](dataset-yaml.md#params)) | Nothing when the link is not meant to be parameters. When it is (a calibration group kept once and linked into each entity), name it under `params.groups`: a group a path names is read wherever it leads, `{groups: {own: /, calibration: /calibration}}`. A link written in the params group itself is read as it always was, so moving it there is the other way on |
| `WARNING: <file>:<group>/<name> links back to <group>, which is already being read; skipped` | With `recursive: true`, a link inside the params group names a group above it on the path being read (`/entry/sub/up -> /entry`). Following it would never end | Nothing; the rest of the group is read. Repair the link if it was meant to point elsewhere |
| `WARNING: <file>:<group>/<name> links into <group>, an entity group of this dataset; skipped` | With `recursive: true` under `groups`, a second HDF5 name (a hard link) inside one entity group names a group that is itself an entity of the dataset, or a group `entity_group` matched | Nothing; that group is registered as its own entity. Name it under `params.groups` if its values belong to this entity too |
| `<file>: artifact '<t>' has N rows but '<first>' has M; every artifact's leading axis is the entity axis` | A batch file whose arrays disagree on axis 0 | It is not one batch; split the artifact out or fix the file |
| `<file>: entity_group '<pattern>' matches no group` | The path or glob names no group in that file: a typo, a different case (case matters), a dataset where a group was meant, or a file unlike the others | List the file's groups (`h5py.File(p).visit(print)`) and correct `entity_group`, or narrow `pattern` to the files that have it |
| `<file>: no groups under entity_group '<pattern>' to treat as entities` (with `(after exclude_groups)` when it is set) | The matching groups hold datasets only, or `exclude_groups` leaves out every subgroup | Point `entity_group` one level higher, or loosen `exclude_groups` |
| `<file>:/<group>: params.group '<path>' climbs N levels from an entity group M levels below the file root, so above the root` (or `params.groups.<name>`) | The path has more `..` segments than the entity group is deep | Remove the extra `..`: M of them reach the file root. A path inside the file root is written after them: `../../calibration` |
| `<file>:/<group>: params.group '<path>' names no group or dataset there, and under `from: attrs` a group that a container lacks is an error` (or `params.groups.<name>`) | Under `from: attrs` the group's own attributes are the parameters, so a file (or entity group) without that group has none of them; the message names the container that lacks it. Under `from: datasets` the same missing group leaves null columns instead | Follow the `Fix:` line: narrow `pattern` (and `entity_group`) to the containers that hold the group, name a group every one of them has, or read these parameters with `from: datasets` |
| A parameter from a group beside the entity groups is missing, or belongs to another entity | A 1-D array there is one value per entity only when its length equals the number of sibling entity groups after `exclude_groups`; any other length is skipped without a message. The values pair with the siblings in text order, so `scan_10` comes before `scan_2` ([the `groups` fields](dataset-yaml.md#sourcegroups)) | Count the subgroups beside the entity group, add the ones that are not entities to `exclude_groups`, and check that the names are zero-padded. When they are not, text order does not follow the array: leave the array out with `exclude` and say so in the description. A group beside the entity groups is read through its own path: `../calibration` |
| `<file>: no parameters found, so no identity` | `params` points at a group with no scalars, and identity is `params` | Point `params` at the right group, take the values from the path with `params.location` ([parameters from the location](../explanation/sources.md#parameters-from-the-location)), declare `params: null` (valid for `files`, `batch` and `groups`), or set `identity: provenance` |
| `<file>: its location '<location>' does not match params.location '<expression>'` (the entity is named `<file>:/<group>` for `groups`, `<file> row <i>` for `batch`) | One entity's location does not fit the expression: a file named unlike the rest, or an expression written for a file name when a `groups` location ends in `:/<group path>` and a `batch` location in `:<row number>` | Try it on the location the message quotes, `re.search(expression, location)`. Widen the expression, or narrow `pattern` so that the odd file is not matched |
| `<file>: params.location names '<n>', and '<key>' is also read inside the file` (or `inside the entity group`) | A named group has the name of a parameter or a `<field>_<attr>` label read in the container, or of the parent of a dotted key (`instrument` for `instrument.Ei`), so one value would hide the other | Rename the group in `location`, or leave the inner value out with `exclude` |
| `<KEY>: N entities share K uids; every entity must be distinct` | Repeated parameter sets under `identity: params`; a pattern or `entity_group` matching the same thing twice under `provenance`; table rows that repeat the `id` value(s) | For every shared uid the report says where each entity came from (for a table, the id values and the row numbers, counted from 0 after the header), then each column or parameter whose values differ, one value per entity, and under `params` the parameters they share. Its `Fix:` line depends on the source: [the fix for each source](#collisions-the-fix-for-each-source) |
| `<file>: parameter '<name>' is named like a locator` (or `label '<name>' (attribute '<a>' of parameter '<p>')`) | A parameter, an attribute label, a `params.groups` name or a named group of `params.location` is `path_<type>`, `dataset_<type>` or `index_<type>` for an artifact `type` the YAML declares. Registration writes that artifact's locator under the same name ([reserved names](manifest.md#reserved-names)) | Follow the `Fix:` line. For a dataset, list its HDF5 path in `params.exclude` (for a label, the path of the dataset that carries the attribute), or rename it in the file. For a parameter read `from: attrs`, list `<group path>/<attribute>` in `params.exclude`, or rename the attribute in the file. For a `params.groups` name, rename it; for a named group of `params.location`, rename the group |
| `<table>: id column '<c>' not among [...]` | An `id` entry names no column of the table | Correct the name; case and spaces count |
| `shared axis '<t>': dataset '...' not found in any of the N files` | Wrong path for a `shared` entry | Correct the path |
| `shared axis '<t>' (...) differs between a.h5 and b.h5` | The array is not actually shared; it varies per entity | It is an artifact, not an axis. Move it to `artifacts` |
| `note: column '<c>' of entities.parquet holds values of more than one kind across rows; stored as JSON text` (or `artifacts.parquet`) | A parameter changes type across files (a number in one, a string or an array in another; a `params.location` group that captures only digits for some entities and other text for others), or one attribute name is a list for one artifact type and a scalar for another. Parquet has one type per column ([columns of more than one kind](manifest.md#columns-of-more-than-one-kind)) | The manifest is written, and that column holds each value's JSON text, so a query on the key compares text. For a parameter, dump two files and diff them, fix the inconsistent file and regenerate; for a location group, make it capture the same kind of text everywhere. For one attribute name shared by two artifact types, nothing to do |
| `note: <path>@<attr> is not carried as array metadata: HDF5 object references cannot be stored` (or `as a label`, for a parameter field's attribute) | The attribute is an HDF5 object or region reference, or holds one. A reference points inside one file, so no catalog can follow it | Nothing to do: the array and the other attributes are carried. Write what a reader needs as a path or a name in another attribute |
| `WARNING: /path@attr is not carried as array metadata` | A dataset attribute is named like a manifest column: `type`, `shape`, `dtype`, `file`, `dataset`, `index`, `uid` | Harmless; the attribute is dropped, not the array. Rename it in the file if you need it carried |
| Entity or artifact counts differ from what you expected | The glob matched extra or fewer files; a batch leading axis is not what you assumed (it is read from `artifacts[0]`); `entity_group` or `exclude_groups` is wrong | Count the files, dump one file, fix, regenerate. Formulas below |

### Collisions: the fix for each source

| Source | The report's `Fix:` line | What to do |
|---|---|---|
| `table` | list one of the columns that differ, per uid, in `id`, with an example list | Make `id` a list, `id: [specimen, replicate]`, so that together the columns are unique. When the rows are equal in every column (`no column differs`), no set of columns is unique: de-duplicate the table. The contract does not number rows ([why](../explanation/identity.md)) |
| `files`, `batch`, `groups` under `identity: provenance` | the pattern or `entity_group` is matching the same thing twice | Tighten `pattern` or `entity_group` |
| `files`, `batch`, `groups` under `identity: params` | add a distinguishing parameter, from inside the container or from its path with `params.location`, or set `identity: provenance` | Add a run number or seed to the parameters. When only the file, directory or group name or the batch row tells the entities apart, take it with `params.location` ([parameters from the location](../explanation/sources.md#parameters-from-the-location)). Or write `identity: provenance` under the source |

### Expected counts

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

---

## `tilewright register`

| Message | Cause | Fix |
|---|---|---|
| `<yaml> has no 'key:' yet` | `manifest` has not been run on this YAML | Run it |
| `no manifests for '<KEY>' in <dir>` | `manifest` was not run, or was run on a YAML with a different label | Run `tilewright manifest` on this YAML |
| `the manifests in <dir> were generated from a different source block than <yaml> now has` | The source block changed after the manifests were built | Rerun `tilewright manifest` |
| `declares shared axes but the manifests for '<KEY>' carry none` | Manifests predate the `shared` entries | Rerun `tilewright manifest` |
| `ERROR: <yaml>: could not register '<KEY>': TypeError: ...` | The Tiled client cannot encode a value under `metadata`, such as an integer beyond 64 bits (`Integer exceeds 64-bit range`). A `TypeError` raised anywhere else is a bug and prints its traceback instead | Quote the value in the YAML so that it is a string. Report a traceback as a bug |
| `'<KEY>' already holds different data` | Another dataset (or a copy of this one in another directory) is registered under this label; or this table's `id` changed to, from or between lists since it was registered ([identity and keys](../explanation/identity.md)). Both fingerprints are printed | Choose a different label. For your own table after an `id` change: `tilewright delete <KEY>`, then `register` |
| `'<KEY>' was registered before fingerprints existed` | The container predates the fingerprint convention | If it is this dataset, `--adopt`; otherwise choose a different label |
| `dataset '<KEY>' exists with storage='external' but this run would register storage='uploaded'` (or the reverse) | The key was registered with the other transport, and a dataset is one or the other | `tilewright delete <KEY>` and re-register, or choose a new label |
| `415 ... mimetype application/x-hdf5-broker is not one that the Tiled server knows how to read` | The server's config has no `adapters_by_mimetype` entry for the adapter, or `tilewright` is not importable in the server's environment | Server side: [How to host a server](../host-a-server.md). On a server you do not run, ask its operator |
| `WARNING ent=... half-registered: k of n artifacts on the server; registering the rest` | A previous run died partway through that entity | Nothing; this run attaches the missing artifacts. Check that `Artifact errors` is `0` |
| `WARNING ent=... art=...: file changed on disk since registration`, then `ERROR: N artifact(s) ... changed on disk` and exit `1` | The source file's modification time or size differs from what was stamped at registration: the arrays were regenerated. An existing artifact is never rewritten, and `register` cannot open files to know which side is right | Rebuild the dataset: `tilewright manifest`, `tilewright delete <KEY>`, `tilewright register`. The message prints the three commands |
| `note: <dataset>/<entity> <key> = inf is not a JSON number; stored as null` (with a count over the run; or `<dataset>/metadata` for the YAML's own metadata) | A value in the dataset metadata, an entity's parameters, a label or an artifact's metadata is `inf` or `-inf`, which no JSON number can hold, so the server stores null ([values the transport cannot carry](manifest.md#values-the-transport-cannot-carry)) | Nothing breaks: the entity is registered and its uid is unchanged, since the manifest keeps the value. To keep the information in the catalog, write it as a string in the file or the YAML, or leave the key out with `params.exclude`, then regenerate and re-register |
| `Cannot reach Tiled server at <URL>` | The server is not running, the URL is wrong, or it is not reachable from this host | Check `--url` / `TILED_URL` and reachability |
| `401` naming the scopes it wanted | The API key lacks a scope: write for `register`, delete for `delete` | The message names required and held scopes; use a key that has them |

`Artifact errors: 0` in the summary block says nothing about whether the server can read
a byte. See the read-back below.

---

## Reads through the server

| Symptom | Cause | Fix |
|---|---|---|
| Registration clean, **every** read returns HTTP 500 | One of: the server is missing `adapters_by_mimetype`; `server_base_dir` is unset or wrong; `directory` is not under the server's `readable_storage`; `directory` was written through a symlink; or the file is unreadable by the server process. Nothing opens the pointer until a read, so `manifest` and `register` both pass on all of these | [Step 3 of the publishing guide](../ONBOARDING.md#3-make-local-and-server-paths-agree). On a server you run, the log line `Refusing to serve file://... because it is outside the readable storage area` names the offending path. Then regenerate, `tilewright delete` the dataset, and register again |
| Read returns 500 for **some** entities only | Stale manifest: those files changed shape or dtype since `manifest`, and the adapter re-checks both against the file | Regenerate, delete, re-register |
| Read returns 500 for **some artifact types** only, and the server log says `can't open directory (.../plugin)` or `required filter ... is not registered` (`tilewright.client.load` raises the same `OSError`) | The array is compressed with an HDF5 filter that neither HDF5 nor [`hdf5plugin`](https://pypi.org/project/hdf5plugin/) ships. Every TileWright read path loads `hdf5plugin`'s filters (LZ4, Bitshuffle, Blosc, Zstd, ...), so this is a rarer one | Install that filter's HDF5 plugin and point `HDF5_PLUGIN_PATH` at its directory, in the server's environment and in a direct reader's. `h5py.File(p)[dataset].id.get_create_plist().get_filter(0)` names the filter |
| `KeyError: '<KEY>'` right after a clean register | You are reading a different server than you registered into | Use the same URL and key for both |
| Array shape is not what you expect | For a `batch` source the manifest records the *per-entity* shape, leading axis dropped | Expected; see [sliced reads](../explanation/data-model.md#an-entity-is-a-slice) |

The symlink case is worth restating because it is silent and expensive: the server's
containment check compares the path **as written** against `readable_storage` and never
resolves links, so a logical path that merely symlinks into an allowed root is refused.
Write `directory` as a physical path (`pwd -P`, `readlink -f`).
