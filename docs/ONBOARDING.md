# How to publish a dataset

Turn a directory of HDF5 files into a dataset in a Tiled catalog: searchable by its
physics, readable from anywhere.

**Before you start:** [install `tilewright`](install.md), check the files match one of the
[four sources](explanation/sources.md), and export `TILED_URL` and `TILED_API_KEY`.

## Pick a transport first

This decision changes two steps below; everything else is the same either way.

| | The server reads your files | You upload the arrays |
|---|---|---|
| **Command** | `tilewright register` | `tilewright register --upload` |
| **Use when** | The data is on a filesystem the Tiled server can open, the normal case for facility storage | The server cannot see your disk: a laptop, another institution |
| **What is registered** | Pointers. No array bytes move | The arrays themselves, streamed into the server's storage |
| **Afterwards** | The files stay where they are, and stay load-bearing | The server owns the bytes; your local files are no longer involved |

A dataset is one transport or the other; `tilewright register` refuses to mix them.

<figure class="tw-diagram">
--8<-- "diagrams/pipeline.svg"
<figcaption>What each step reads and writes. Only the last one needs a running server.</figcaption>
</figure>

## 1. Author the dataset YAML

The YAML is the contract: enough about your files to register them without knowing
anything about your science. It lives **with the data**, at
`<data root>/.tilewright/datasets/<KEY>.yml`, so it travels with what it describes.
`tilewright manifest` writes `key` for you, so name the file after the key you expect
(`slug(label)`: `Okafor NiPS3 Powder` becomes `OKAFOR_NIPS3_POWDER`).

### With an agent (recommended)

A clone ships an `/onboarding` skill at `.claude/skills/onboarding/`. From the repository
root in Claude Code:

```
/onboarding
```

Tell it where your data is and what you know about it: the instrument or code that
produced it, the material, who to name as contact, a paper, a README. It opens your HDF5
with `h5py` and drafts the YAML from what is there, then asks you the questions the data
cannot answer. Uploading? Add one line:

> This is remote registration: the server cannot see my filesystem, so we will use
> `tilewright register --upload`.

**You are still the reviewer.** An agent reads shapes and dtypes off your files;
`method`, `material`, and `producer` are provenance claims only you can confirm.

### By hand

```bash
mkdir -p .tilewright/datasets
cp <TileWright>/examples/datasets/files.yml .tilewright/datasets/MY_DATASET.yml
```

Then edit:

- **`label`**: distinctive. On a shared server, include your surname or group:
  `Okafor NiPS3 Powder`, not `My Dataset`. Two people picking the same name land on the
  same key, and the second registration is refused.
- **`metadata`**: `method`, `data_type`, `material` required; `contact` and
  `description` expected. Prefer ids from `src/tilewright/vocabulary.yml`; unknown ones
  warn, not fail. Write the description for a person deciding whether to open the
  dataset, and say what a reader should know before trusting the data.
- **`source`**: one tag, `files`, `batch`, `groups`, or `table`, with its `directory`
  and where the parameters are. Repeated measurements with identical parameters need a
  distinguishing parameter or `identity: provenance`; a table whose `id` column repeats
  needs more columns in `id`
  ([identity and keys](explanation/identity.md)).
- **`artifacts`**: one per array an entity exposes; `optional: true` if some entities
  lack it. Arrays common to *every* entity, like an energy axis, go under `shared`.

NeXus files start from `examples/datasets/files_nexus.yml`. Full field list:
[the dataset YAML reference](reference/dataset-yaml.md).

### The two fields the transport changes

=== "Server reads the files"

    `directory` is the root as **you** see it; `server_base_dir` is the same root as
    **the server** sees it. Step 3 gets them to agree.

=== "Upload from my machine"

    `directory` is the path on **your** machine, where `--upload` reads from. Omit
    `server_base_dir`; the server never opens your files.

    ```yaml
    label: Okafor NiPS3 Powder
    metadata:
      method: [INS]
      data_type: experimental
      material: NiPS3
      contact: "Ada Okafor <okafor@example.org>"
    source:
      files:
        directory: /home/me/experiments/run42   # local to YOU
        pattern: "*.h5"
    artifacts:
      - {type: spectrum, dataset: /spectrum}
    ```

## 2. Build the manifests

From the data root:

```bash
tilewright manifest .tilewright/datasets/MY_DATASET.yml
```

It validates the contract (every problem at once, one sentence each), writes `key:` into
the YAML, scans the files, and records each artifact's path, shape and dtype in
[two Parquet manifests](reference/manifest.md) under `.tilewright/manifests/<KEY>/`.
Nothing has touched the network yet. `--check` validates and stops.

**Check the reported entity and artifact counts against your files.** If they are wrong,
fix the YAML and rerun: usually a broad `pattern`, the wrong batch axis, or the wrong
entity group. The formulas are in [errors and warnings](reference/errors.md#expected-counts).

## 3. Make local and server paths agree

<a id="paths-where-your-view-and-the-servers-view-differ"></a>

=== "Upload from my machine"

    Nothing to do: no path has to agree with anything, `server_base_dir` is ignored, and
    the stock Tiled adapter serves the uploaded arrays. The receiving server needs
    `writable_storage`; see [How to host a server](host-a-server.md).

=== "Server reads the files"

    Three settings have to describe the same bytes:

    <figure class="tw-diagram">
    --8<-- "diagrams/paths.svg"
    <figcaption>Two of the three are in your dataset YAML; the third is the server's own config.</figcaption>
    </figure>

    | Setting | Filesystem | Purpose |
    |---|---|---|
    | `directory` | yours | Root scanned by `tilewright manifest` |
    | `server_base_dir` | server | Equivalent root stored in catalog pointers |
    | `readable_storage` in the server config | server | Roots the server may read |

    Keep the path below each root identical:

    ```yaml
    source:
      files:
        directory: /home/me/rixs/data/my_dataset
        server_base_dir: /mnt/shared/rixs/data/my_dataset
    ```

    - Add the **server-side** root to `readable_storage`.
    - Use physical paths (`pwd -P`, `readlink -f`), not symlinks.
    - Sharing a filesystem? Omit `server_base_dir`; it defaults to `directory`.

    The server also needs TileWright's array adapter, or every read returns HTTP 500
    after a registration that looked fine; [How to host a server](host-a-server.md) has
    the config line.

## 4. Register the dataset

Register a small sample first, then the rest:

=== "Server reads the files"

    ```bash
    tilewright register -n 5 .tilewright/datasets/MY_DATASET.yml
    tilewright register .tilewright/datasets/MY_DATASET.yml
    ```

    No array bytes move: registration reads the manifest and never opens an HDF5 file,
    which is what makes ten thousand entities cheap.

=== "Upload from my machine"

    ```bash
    tilewright register --upload -n 5 .tilewright/datasets/MY_DATASET.yml
    tilewright register --upload .tilewright/datasets/MY_DATASET.yml
    ```

    This moves the real data, so wall-clock scales with size and uplink, not entity
    count. Parameters become queryable metadata, arrays stream to the server, shared axes
    stream once each, and the container is stamped `storage: uploaded`.

Either way registration is incremental: an existing entity is skipped, so the second
command continues from the first and an interrupted run resumes.

If the key already exists on the server, `register` compares fingerprints. The same data
proceeds; different data under your label is refused, with both fingerprints and the
existing container's description printed, and you pick another label
([identity and keys](explanation/identity.md)).

Three kinds of change, three procedures:

| You changed | Do |
|---|---|
| Dataset metadata in the YAML (description, contact, a facet) | `tilewright register --update`. One node is patched; Tiled keeps the previous metadata as a revision |
| Nothing, but more entities exist (an interrupted run, new files) | `tilewright manifest --append`, then `register`. Existing entities are skipped |
| The files, a path, a shape or dtype | `tilewright manifest`, `tilewright delete MY_DATASET`, `register`. Existing artifacts are never rewritten in place, and a rerun that finds a registered artifact's source file changed on disk stops and prints these three commands |

## 5. Read it back

Registration never opens a pointer-registered array, so a read through the server is the
real check. From any machine that can reach it:

```python
from tiled.client import from_uri

client = from_uri("<URL>", api_key="<KEY>")
ds = client["MY_DATASET"]              # the key manifest wrote

# A dataset's children are its entities *plus* one array per shared axis, so drop
# the axes before taking "the first entity".
shared = {k.removeprefix("shared_dataset_") for k in ds.metadata if k.startswith("shared_dataset_")}
entities = [k for k in ds if k not in shared]
entity = ds[entities[0]]

len(entities)                          # the entity count manifest printed (or -n)
print(dict(ds.metadata))               # the facets you wrote, plus storage/fingerprint/registered_at
print(dict(entity.metadata))           # this entity's physics parameters
print(entity["spectrum"][:].shape)     # the array itself, at the shape the manifest recorded
[ds[k][:].shape for k in shared]       # every shared axis
```

Metadata on the dataset, parameters on the entity, an array at the shape you registered:
the whole contract, proven. Collaborators need nothing beyond the Tiled client.

Next: [read a registered catalog](using-the-catalog.md).

## 6. Start over

```bash
tilewright delete MY_DATASET
```

This removes the catalog entries and, for an uploaded dataset, the arrays the server
stored, since the catalog is their only home. Your HDF5 files are never touched.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `contract error: ...` | Each line names the field and the fix; the [YAML reference](reference/dataset-yaml.md) has every field |
| `has no 'key:' yet` | Run `tilewright manifest` first |
| `N entities share K uids` | The report shows what differs and a fix for your source: a distinguishing parameter or `identity: provenance`; for a table, another column in `id` |
| `already holds different data` | Another dataset owns that label; choose a different one |
| `no manifests for '<KEY>'` | Run `tilewright manifest` on this YAML |
| Entity or artifact counts are wrong | Check `pattern`, the batch leading axis, or `entity_group` |
| Registration succeeds but every read returns HTTP 500 | The server is missing the adapter, or `server_base_dir` / `readable_storage` / a symlinked path is wrong (step 3). Fix, then regenerate, delete, register again |

Every other message with a specific cause is in [errors and warnings](reference/errors.md);
flags and exit codes are in [the `tilewright` reference](reference/cli.md).
