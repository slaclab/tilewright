# Errors and warnings

Every message from `tilewright register`, `tilewright delete` and reads through the
server that has a specific cause, in the order of the pipeline that raises it. Messages from
`tilewright manifest` are part of onboarding, in
[the onboarding skill's errors page](https://github.com/slaclab/TileWright/blob/main/skills/onboarding/reference/errors.md).

---

## `tilewright register`

| Message | Cause | Fix |
|---|---|---|
| `<yaml> has no 'key:' yet` | `manifest` has not been run on this YAML | Run it |
| `no manifests for '<KEY>' in <dir>` | `manifest` was not run, or was run on a YAML with a different label | Run `tilewright manifest` on this YAML |
| `the manifests in <dir> were generated from a different source block than <yaml> now has` | The source block changed after the manifests were built | Rerun `tilewright manifest` |
| `declares shared axes but the manifests for '<KEY>' carry none` | Manifests predate the `shared` entries | Rerun `tilewright manifest` |
| `ERROR: <yaml>: could not register '<KEY>': TypeError: ...` | The Tiled client cannot encode a value under `metadata`, such as an integer beyond 64 bits (`Integer exceeds 64-bit range`). A `TypeError` raised anywhere else is a bug and prints its traceback instead | Quote the value in the YAML so that it is a string. Report a traceback as a bug |
| `'<KEY>' already holds different data` | Another dataset (or a copy of this one in another directory) is registered under this label; or this table's `id` changed to, from or between lists since it was registered ([identity and keys](https://github.com/slaclab/TileWright/blob/main/skills/onboarding/reference/identity.md)). Both fingerprints are printed | Choose a different label. For your own table after an `id` change: `tilewright delete <KEY>`, then `register` |
| `'<KEY>' was registered before fingerprints existed` | The container predates the fingerprint convention | If it is this dataset, `--adopt`; otherwise choose a different label |
| `dataset '<KEY>' exists with storage='external' but this run would register storage='uploaded'` (or the reverse) | The key was registered with the other transport, and a dataset is one or the other | `tilewright delete <KEY>` and re-register, or choose a new label |
| `415 ... mimetype application/x-hdf5-broker is not one that the Tiled server knows how to read` | The server's config has no `adapters_by_mimetype` entry for the adapter, or `tilewright` is not importable in the server's environment | Server side: [How to host a server](../host-a-server.md). On a server you do not run, ask its operator |
| `WARNING ent=... half-registered: k of n artifacts on the server (N more serve nothing); registering the m missing` | A previous run died partway through that entity. `k` counts only the nodes that serve their row; the `(N more serve nothing)` clause appears when the row below counted some, and those `N` are not among the `m` this run registers — an existing artifact is never rewritten | Nothing for the `m` missing ones; this run attaches them. Check that `Artifact errors` is `0` **and** that `Broken nodes` is `0`: a run can print this line, end with `Artifact errors: 0` and still exit `1` with `Broken nodes: N`, which the row below is about |
| `WARNING ent=... art=...: the node on the server cannot serve this artifact (...)`, counted as `Broken nodes` in the summary, then `ERROR: N artifact(s) ... serve nothing` and exit `1` | That key is a child of the entity already, but its node does not hold the source the manifest names — it reads another file, another path inside one, or no source at all. A key's presence is not proof that it reads, and a run before this check skipped such a node for ever and reported the dataset complete. A node created by a run of this version is either whole or gone, so this is a node from an older run, or one whose files moved | Delete each node the warning names (`tilewright delete <KEY> <ENTITY> <ARTIFACT>`) and register again. An existing artifact is never rewritten, so nothing is repaired in place |
| `ERROR ent=... art=...: <cause>. Fix the cause and register again; this run leaves nothing on the server for it` | The artifact's creation failed. Whatever the server kept for that key was removed, so a later run registers it cleanly | Fix the cause the message names, then register again |
| `... and the node it left on the server could not be removed (...), so a later run would skip that key` | The creation failed **and** the node it left could not be deleted (no delete scope, say) | Delete that node by hand (`tilewright delete <KEY> <ENTITY> <ARTIFACT>`), then register again |
| `WARNING ent=... art=...: file changed on disk since registration`, then `ERROR: N artifact(s) ... changed on disk` and exit `1` | The source file's modification time or size differs from what was stamped at registration: the arrays were regenerated. An existing artifact is never rewritten, and `register` cannot open files to know which side is right | Rebuild the dataset: `tilewright manifest`, `tilewright delete <KEY>`, `tilewright register`. The message prints the three commands |
| `note: <dataset>/<entity> <key> = inf is not a JSON number; stored as null` (with a count over the run; or `<dataset>/metadata` for the YAML's own metadata) | A value in the dataset metadata, an entity's parameters, a label or an artifact's metadata is `inf` or `-inf`, which no JSON number can hold, so the server stores null ([values the transport cannot carry](https://github.com/slaclab/TileWright/blob/main/skills/onboarding/reference/manifest.md#values-the-transport-cannot-carry)) | Nothing breaks: the entity is registered and its uid is unchanged, since the manifest keeps the value. To keep the information in the catalog, write it as a string in the file or the YAML, or leave the key out with `params.exclude`, then regenerate and re-register |
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
