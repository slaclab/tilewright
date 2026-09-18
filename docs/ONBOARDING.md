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

`<TileWright>` is a checkout. Installed [without one](install.md#no-checkout) there is
nothing to copy, so write the file from the skeleton and the field tables in
[the dataset YAML reference](reference/dataset-yaml.md) instead; the rest of this guide is
the same.

Then edit:

- **`label`**: distinctive. On a shared server, include your surname or group:
  `Okafor NiPS3 Powder`, not `My Dataset`. Two people picking the same name land on the
  same key, and the second registration is refused. See the key the label slugs to before
  you commit to it: `tilewright manifest --check` prints it, and an accent, a hyphen or an
  apostrophe in a name comes out as `_`
  ([the rule](reference/dataset-yaml.md#top-level)). If that spelling is not one you want
  pasted around a shared server, write the name plainly in the label and keep it as it is
  really spelled in `contact`, or distinguish the dataset with a group, instrument or
  project token instead of a surname.
- **`metadata`**: `method`, `data_type`, `material` required; `contact` and
  `description` expected. **Nothing fills these in from your files.** Dataset-level facts
  the producer left as HDF5 root attributes (`@title`, `@source`, `@institution`) never
  reach `metadata` by themselves — a `params` block reads per-entity values, not
  dataset-level ones — so copy the ones worth keeping into the YAML by hand, and say in
  the `description` that they came from the files rather than from a person. Prefer ids
  from the vocabulary (`vocabulary.yml`: under `src/tilewright/` in a checkout, and beside
  the installed package otherwise); unknown ones warn, not fail. Write the description for
  a person deciding whether to open the dataset, say what a reader should know before
  trusting the data, and give every number in it a key
  ([what each field means, and what counts as a number](reference/dataset-yaml.md#metadata)).
- **`source`**: one tag, `files`, `batch`, `groups`, or `table`, with its `directory`
  and where the parameters are: inside the files, or only in their names, which
  `params.location` reads
  ([parameters from the location](explanation/sources.md#parameters-from-the-location)),
  or, for `groups`, beside the entity groups
  ([nested entity groups](explanation/sources.md#nested-entity-groups-and-values-beside-them)).
  Repeated measurements with identical parameters need a
  distinguishing parameter or `identity: provenance`; a table whose `id` column repeats
  needs more columns in `id`
  ([identity and keys](explanation/identity.md)).
- **`artifacts`**: one per array an entity exposes; `optional: true` if some entities
  lack it. A `type` may hold spaces, dots and non-ASCII letters, but not `/`, `?` or `#`
  ([the full rule](reference/dataset-yaml.md#artifacts)). A group that holds many arrays
  takes one entry, `{type: "{name}", group: /frames}`
  ([many arrays in one group](explanation/sources.md#many-arrays-in-one-group)).
  Arrays common to *every* entity, like an energy axis, go under `shared`.

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

**How long a pointer run takes.** Cheap is not instant. Every entity container and every
artifact is one HTTP round trip, so the time follows the number of *nodes* —
entities × artifacts, plus one per shared axis — and not the bytes on disk. A few tens of
nodes a second is the order of magnitude for a server on a SQLite catalog, which makes ten
thousand entities minutes and a hundred thousand hours. Measure your own rate rather than
trusting that: time `tilewright register -n 100`, divide, and multiply out. Two levers if
it matters: `--max-workers N`, which helps a dataset of many entities and hardly one of
few entities and very many arrays ([the flags](reference/cli.md#tilewright-register) say
why), and the run's own resumability — a long one can simply be started again. Reading
back is not affected: a query answers from the catalog database, at any size.

If the key already exists on the server, `register` compares fingerprints. The same data
proceeds; different data under your label is refused, with both fingerprints and the
existing container's description printed, and you pick another label
([identity and keys](explanation/identity.md)).

Three kinds of change, three procedures:

| You changed | Do |
|---|---|
| Dataset metadata in the YAML (description, contact, a facet) | `tilewright register --update`. One node is patched; Tiled keeps the previous metadata as a revision |
| Nothing, but more entities exist (an interrupted run, new files) | `tilewright manifest --append`, then `register`. Existing entities are skipped |
| The files, a path, a shape or dtype, a table's `id` | `tilewright manifest`, `tilewright delete MY_DATASET`, `register`. Existing artifacts are never rewritten in place, and a rerun that finds a registered artifact's source file changed on disk stops and prints these three commands |

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

spectrum = entity["spectrum"]          # the array client: no bytes have moved yet
print(spectrum.shape, spectrum.dtype)  # the shape and dtype the manifest recorded
corner = (slice(0, 2),) * spectrum.ndim   # at most 2 along *every* axis, at any rank
print(spectrum[corner])                # a corner: the server slices, these bytes cross
[ds[k].shape for k in shared]          # every shared axis
```

Ask the array client for `.shape` and read a **small slice** — built from `.ndim`, so the
corner means the same thing at every rank: 2×2 of a rank-2 artifact, and of a rank-3 one
the 2×2×2 block at the origin, rather than the two rows out of two different planes that a
literal `[0:2, 0:2]` returns without complaining. `spectrum[:]` would pull the whole array
over HTTP, which for a multi-gigabyte artifact is a long wait and proves nothing the slice
does not: both go through the same adapter, the same file and the same pointer. Compare
the slice with the same corner read from the HDF5 by hand if you want the values checked
too.

Metadata on the dataset, parameters on the entity, an array at the shape you registered:
the whole contract, proven. Collaborators need nothing beyond the Tiled client.

A `table` dataset has no artifact to read, so its proof is the other three: the entity
count, one row's metadata, and a `Key` search that returns the rows you expect
([search](using-the-catalog.md#search)).

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
| `already holds different data` | Another dataset owns that label; choose a different one. If it is your table and you changed its `id`, delete it and register again (step 4) |
| `no manifests for '<KEY>'` | Run `tilewright manifest` on this YAML |
| Entity or artifact counts are wrong | Check `pattern`, the batch leading axis, or `entity_group` |
| Registration succeeds but every read returns HTTP 500 | The server is missing the adapter, or `server_base_dir` / `readable_storage` / a symlinked path is wrong (step 3). Fix, then regenerate, delete, register again |

Every other message with a specific cause is in [errors and warnings](reference/errors.md);
flags and exit codes are in [the `tilewright` reference](reference/cli.md).
