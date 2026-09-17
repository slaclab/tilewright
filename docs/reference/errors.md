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
| `contract error: key '<K>' does not match slug(label)` | `label` changed after the key was written | Restore the label, or delete the `key:` line and rerun. A drifted key is never silently rewritten, because the old key may already hold registered data |
| `contract error: a 'table' source has no readable arrays: remove 'artifacts'` | `artifacts` on a table source | Remove it |
| `contract error: artifact types must be unique` | Two artifacts or shared axes share a `type` | Rename one; types become node keys |
| `note: metadata.<field> '<v>' is not in the vocabulary` | A facet value with no canonical id | Non-fatal by design ([the soft vocabulary](../explanation/vocabulary.md)). Prefer an id so the dataset lands on the same facet as everyone else's |

## `tilewright manifest`: the data

| Message | Cause | Fix |
|---|---|---|
| `no files match '<pattern>' under <directory>` | Wrong directory or pattern | `ls` the directory; the default pattern is `**/*.h5` |
| `OSError: Unable to open file ... file signature not found` | The pattern matched a non-HDF5 sibling: a NetCDF twin, a Parquet sidecar, a `.gz` | Tighten `pattern` |
| `<file>: artifact type=... dataset '...' not found (mark it 'optional: true' if some entities lack it)` | Wrong HDF5 path, or an array that only some entities have; in `groups`, an absolute path where a group-relative one is expected | Dump one file (`h5py.File(p).visititems(print)`) and correct `dataset`, or add `optional: true` |
| `<file>: artifact '<t>' has N rows but '<first>' has M; every artifact's leading axis is the entity axis` | A batch file whose arrays disagree on axis 0 | It is not one batch; split the artifact out or fix the file |
| `<file>: no parameters found, so no identity` | `params` points at a group with no scalars, and identity is `params` | Point `params` at the right group, declare `params: null`, or set `identity: provenance` |
| `<KEY>: N entities share K uids; every entity must be distinct` | Repeated parameter sets under `identity: params`, or a pattern matching the same thing twice under `provenance` | The message names colliding entities and their shared parameters. Add a distinguishing parameter (run number, seed) or set `identity: provenance` |
| `<file>: parameter '<name>' is named like a locator` (or `label '<name>' (attribute '<a>' of parameter '<p>')`) | A parameter, an attribute label or a `params.groups` name is `path_<type>`, `dataset_<type>` or `index_<type>` for an artifact `type` the YAML declares. Registration writes that artifact's locator under the same name ([reserved names](manifest.md#reserved-names)) | Follow the `Fix:` line. For a dataset, list its HDF5 path in `params.exclude` (for a label, the path of the dataset that carries the attribute), or rename it in the file. For a `params.groups` name, rename it. For a parameter read `from: attrs`, rename the attribute in the file: `exclude` skips datasets only |
| `shared axis '<t>': dataset '...' not found in any of the N files` | Wrong path for a `shared` entry | Correct the path |
| `shared axis '<t>' (...) differs between a.h5 and b.h5` | The array is not actually shared; it varies per entity | It is an artifact, not an axis. Move it to `artifacts` |
| `pyarrow.lib.ArrowInvalid` while writing the manifest | A parameter changes type across files: scalar in one, string or array in another | Dump two files and diff their parameters; fix the inconsistent file |
| `WARNING: /path@attr is not carried as array metadata` | A dataset attribute is named like a manifest column: `type`, `shape`, `dtype`, `file`, `dataset`, `index`, `uid` | Harmless; the attribute is dropped, not the array. Rename it in the file if you need it carried |
| Entity or artifact counts differ from what you expected | The glob matched extra or fewer files; a batch leading axis is not what you assumed (it is read from `artifacts[0]`); `entity_group` is wrong | Count the files, dump one file, fix, regenerate. Formulas below |

### Expected counts

| Source | Entities | Artifacts |
|---|---|---|
| `files` | files matched by `pattern` (`ls <directory>/<pattern> \| wc -l`) | entities × non-optional `artifacts` entries, plus optional ones where present |
| `batch` | sum over files of the leading axis of `artifacts[0]` | entities × `artifacts` entries |
| `groups` | groups under `entity_group` (or top-level groups), summed over files | entities × `artifacts` entries |
| `table` | rows of the table | 0 |

Plus one artifact row per `shared` axis, reported separately as `shared=S`.

---

## `tilewright register`

| Message | Cause | Fix |
|---|---|---|
| `<yaml> has no 'key:' yet` | `manifest` has not been run on this YAML | Run it |
| `no manifests for '<KEY>' in <dir>` | `manifest` was not run, or was run on a YAML with a different label | Run `tilewright manifest` on this YAML |
| `the manifests in <dir> were generated from a different source block than <yaml> now has` | The source block changed after the manifests were built | Rerun `tilewright manifest` |
| `declares shared axes but the manifests for '<KEY>' carry none` | Manifests predate the `shared` entries | Rerun `tilewright manifest` |
| `'<KEY>' already holds different data` | Another dataset (or a copy of this one in another directory) is registered under this label; both fingerprints are printed | Choose a different label |
| `'<KEY>' was registered before fingerprints existed` | The container predates the fingerprint convention | If it is this dataset, `--adopt`; otherwise choose a different label |
| `dataset '<KEY>' exists with storage='external' but this run would register storage='uploaded'` (or the reverse) | The key was registered with the other transport, and a dataset is one or the other | `tilewright delete <KEY>` and re-register, or choose a new label |
| `415 ... mimetype application/x-hdf5-broker is not one that the Tiled server knows how to read` | The server's config has no `adapters_by_mimetype` entry for the adapter, or `tilewright` is not importable in the server's environment | Server side: [How to host a server](../host-a-server.md). On a server you do not run, ask its operator |
| `WARNING ent=... half-registered: k of n artifacts on the server; registering the rest` | A previous run died partway through that entity | Nothing; this run attaches the missing artifacts. Check that `Artifact errors` is `0` |
| `WARNING ent=... art=...: file changed on disk since registration`, then `ERROR: N artifact(s) ... changed on disk` and exit `1` | The source file's modification time or size differs from what was stamped at registration: the arrays were regenerated. An existing artifact is never rewritten, and `register` cannot open files to know which side is right | Rebuild the dataset: `tilewright manifest`, `tilewright delete <KEY>`, `tilewright register`. The message prints the three commands |
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
| `KeyError: '<KEY>'` right after a clean register | You are reading a different server than you registered into | Use the same URL and key for both |
| Array shape is not what you expect | For a `batch` source the manifest records the *per-entity* shape, leading axis dropped | Expected; see [sliced reads](../explanation/data-model.md#an-entity-is-a-slice) |

The symlink case is worth restating because it is silent and expensive: the server's
containment check compares the path **as written** against `readable_storage` and never
resolves links, so a logical path that merely symlinks into an allowed root is refused.
Write `directory` as a physical path (`pwd -P`, `readlink -f`).
