# The `tilewright` command line

`tilewright` dispatches three subcommands. Run bare or with `-h` / `--help` for the list;
an unrecognized subcommand exits `1`.

```
tilewright <command> [args]

  manifest    Validate a dataset YAML, derive its key, write its Parquet manifests
  register    Register manifests into a running Tiled server over HTTP
  delete      Delete registered data from a running Tiled server
```

Pipeline order is `manifest` → `register`; the walkthrough is
[How to publish a dataset](../ONBOARDING.md). Source: `src/tilewright/cli.py`.

Server-facing commands take the server from `--url` and `--api-key`, or from `TILED_URL`
and `TILED_API_KEY` in the environment. Nothing is read from a file.

---

## `tilewright manifest`

Validates a dataset YAML, writes its key, scans the data, and writes the two Parquet
manifests that registration reads.

```
tilewright manifest YAML_PATH [-o OUTPUT_DIR] [--append] [--check]
```

| Flag | Effect |
|---|---|
| `-o`, `--output-dir DIR` | Write manifests to `DIR` instead of the default |
| `--append` | Keep existing manifests and add only entities whose `uid` is not already present |
| `--check` | Validate the contract, print `contract OK: ...`, and stop; writes nothing |

| | |
|---|---|
| Reads | the YAML, and every file matched by the source's `directory` + `pattern` (or the table) |
| Writes | `key:` into the YAML if absent, as one new line after the `label:` line (before it when the label spans several lines); the rest of the YAML is left as written. When no such line gives the same YAML plus the key (an empty `key:`, a top-level flow mapping), the whole YAML is written out again: comments stay, but the layout does not, and a vocabulary alias is written as its canonical id. `entities.parquet` and `artifacts.parquet` in `<root>/manifests/<KEY>/`, where `<root>` is the YAML's directory, or its parent when the YAML sits in a `datasets/` directory (the `.tilewright/datasets/<KEY>.yml` → `.tilewright/manifests/<KEY>/` layout) |
| Server | not required |

Prints `dataset=<KEY> entities=N artifacts=M shared=S` on success. Contract problems are
printed as one `contract error:` line each, all of them, then exit `1`; a data problem
(file not found, array missing, shared axis differing, duplicate identities, a
parameter named like a locator) names the file and the path and exits `1`.

Each artifact's `shape` and `dtype` are captured here, which is what lets registration run
without opening a single HDF5 file, and why the manifest must be regenerated when the data
changes shape or dtype. See [The Parquet manifest](manifest.md).

---

## `tilewright register`

Registers manifests into a running Tiled server over HTTP. This is the only registration
route.

```
tilewright register YAML [YAML ...] [--url URL] [--api-key KEY] [-n NUM] [--max-workers N]
                    [--upload] [--update] [--adopt]
```

| Flag | Effect |
|---|---|
| `--url URL` | Server URL (default `$TILED_URL`, else `http://localhost:8005`) |
| `--api-key KEY` | API key with write scopes (default `$TILED_API_KEY`) |
| `-n`, `--max-entities NUM` | Register at most `NUM` entities per dataset (default: all) |
| `--max-workers N` | How many **entities** register at once. One entity's artifacts are posted one after another inside its own worker, and the shared axes before the pool starts, so a value above the entity count changes nothing and a dataset of few entities and very many arrays gains little (default: `TILEWRIGHT_MAX_WORKERS`, else `8`) |
| `--upload` | Read the arrays from local HDF5 and write them through the server into its writable storage, instead of registering pointers to files the server reads itself |
| `--update` | Also merge-patch the dataset container's metadata from the YAML. Same data only; the previous version is kept as a Tiled revision |
| `--adopt` | Claim a container registered before fingerprints existed |

| | |
|---|---|
| Reads | each YAML, its manifests, and with `--upload` the HDF5 files themselves |
| Writes | catalog entries on the server; with `--upload`, array data in the server's storage |
| Server | **required** |

- **Validates before connecting.** Every YAML must be a valid contract carrying the key
  `manifest` wrote, and its manifests must match its source block, before the network is
  touched.
- **Checks the key against the server.** A new key is created with `storage`,
  `fingerprint` and `registered_at` stamped. An existing key with the same fingerprint
  proceeds; a different fingerprint is refused with both printed; a container without one
  needs `--adopt` ([identity and keys](../explanation/identity.md)).
- **Incremental.** An entity whose key already exists is skipped, so a re-run resumes
  rather than duplicates. A skipped artifact whose source file changed on disk since it
  was registered (modification time or size, stamped at registration) is reported as
  `Changed on disk` and the command exits `1` with the rebuild steps; nothing is
  rewritten in place.
- **A key's presence is not proof that it reads.** Each artifact already on the server is
  checked against the source its manifest row names — the file, and the path inside it.
  One that holds another source, or none, is reported as `Broken nodes`, named with its
  key, and the command exits `1`; nothing is rewritten in place, so the fix is to delete
  those nodes and register again. An artifact whose creation fails leaves nothing behind:
  what the server kept for that key is removed before the error is counted.
- **Shared axes go first**: the manifest's `uid`-less rows, one array child of the dataset
  container each, over the same transport as entity artifacts. Independent of `-n`; an
  existing axis is skipped.
- **Without `--upload`** the server opens the files itself, so `directory`,
  `server_base_dir`, and the server's `readable_storage` all have to agree. Getting them
  wrong registers cleanly and fails on every read; see
  [How to publish a dataset](../ONBOARDING.md#3-make-local-and-server-paths-agree).
- **With `--upload`**, `server_base_dir` is ignored (announced, not an error) and
  `directory` must exist locally. A dataset cannot mix uploaded and pointer entities.
- **Verifies** the datasets it just registered: container, shared axes, first entity,
  first artifact. That is a structural probe, not a read; the read-back in the publishing
  guide is the proof.

---

## `tilewright delete`

Deletes registered data at one of four granularities.

```
tilewright delete DATASET [ENTITY [ARTIFACT]] [--url URL] [--api-key KEY] [--dry-run] [--yes]
tilewright delete all [--confirm URL] [--dry-run]
```

| Form | Removes |
|---|---|
| `DATASET` | the dataset container and everything under it |
| `DATASET ENTITY` | one entity and its artifacts |
| `DATASET ENTITY ARTIFACT` | one array |
| `all` | every top-level container on the server |

| Flag | Effect |
|---|---|
| `--dry-run` | Print the preview (target, child counts, storage note) and exit without deleting |
| `--yes` | Skip the `y/yes` confirmation for the granular forms |
| `--confirm URL` | For `all`: the server URL, retyped, instead of the interactive prompt; must match exactly |

What is removed depends on the dataset's `storage` marker: an external dataset loses only
its catalog pointers, the HDF5 files on disk are untouched; an uploaded dataset also loses
the array bytes the server holds, since there is no other copy. `all` decides per
container.

Exit status: `0` deleted (or dry run); `1` a target does not exist, or with `all` any
container failed; `2` bad arguments, or a confirmation was needed in a non-interactive
shell without `--yes` / `--confirm`.
