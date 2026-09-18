---
name: onboarding
description: >-
  Onboard a new HDF5 dataset into the Tiled catalog. Reads the contract surface
  (docs/ONBOARDING.md, the pydantic contract, the vocabulary, the example YAMLs), then
  explores the user's data + codebase to draft a first-pass dataset YAML with predicted
  entity/artifact counts, pauses for the user's review, runs `tilewright manifest` and
  compares the counts, pauses again for the go, then registers and proves the result by
  reading it back through the server. Use when the user wants to onboard, register, or add
  a new dataset, or asks to "get ready to onboard a dataset".
---

# Onboarding a dataset

Goal: take a producer's HDF5 dataset and register it into the catalog by authoring **one
dataset YAML** against the contract surface, then running `tilewright manifest` and
`tilewright register`. You onboard by reading the *contract*, never broker *implementation*.

## Step 0 — Read the contract surface (do this first, do not skip)

Read these, in order. They define what a valid dataset is; do not reverse-engineer it from
`manifest.py` / `register.py`:

1. `docs/ONBOARDING.md` — the walkthrough: pick a transport, author, manifest, make paths
   agree, register, read back. It links the source, field, and error references.
2. `src/tilewright/contract.py` — the authoritative field contract (every YAML field, its
   type, whether it is required, what it means).
3. `src/tilewright/vocabulary.yml` — canonical ids + aliases for `method`, `material`,
   `producer`, `project`, `proposal`, `facility`, `data_type`.
4. `examples/datasets/{files,batch,groups,table}.yml` — one worked example per source tag,
   each with its expected counts in the header; `files_nexus.yml` shows a NeXus tree mapped
   onto the contract (several parameter groups → nested metadata).
5. `docs/ONBOARDING.md` step 4, the upload tab — **only if** the server cannot see the
   user's files (they will say so, or you learn it in Step 1). Same contract, different
   transport.

## Step 1 — Report ready, ask for the starting context (and wait)

After reading, tell the user in 2–3 sentences that you understand the contract — the
**four sources** (`files`, `batch`, `groups`, `table`), the **required**
`method`/`data_type`/`material` metadata, and that the **vocabulary is soft** (unknown
values warn, they don't block). Then ask for the starting context you need to explore:

- the **data path** (directory of HDF5 files);
- the **codebase / producer scripts** that generated it, if available (for inferring
  method, producer, material, parameter meanings);
- **who to name as `contact`** for the dataset (`Name <email>`), and whether the
  registrant is that person;
- **where the server runs** relative to the data (same filesystem → pointer registration;
  server can't see the files → `tilewright register --upload`); and
- any other context they want to give (paper, README, prior YAML, etc.).

**This is a conversation — stop and wait for the answer**, even if the data path was
already given in the invocation. What the user tells you here is the *only* source of
metadata besides the data itself (see Step 2). Don't go looking for more on your own.

## Step 2 — Explore the data and codebase

Explore **only two things**: (a) the data path, and (b) the codebase/context the user
named in Step 1. Do **not** hunt for context elsewhere in the repo or its history — not the
`examples/`, not deleted files showing in `git status`, not `git show`/`git log`, not
`config.yml`'s storage roots, not example keys in `README.md`/`CLAUDE.md`, not old
manifests. Those describe *other* datasets and deployments; copying values from them
fabricates provenance for this one. If you notice such a file, ignore it and — if it seems
relevant — *mention* it to the user and let them decide whether to hand it to you.

The same goes for a YAML that already describes **this very dataset** (a prior
`.tilewright/datasets/<KEY>.yml` in the data root, or manifests for it): don't silently
adopt, overwrite, or delete it. Tell the user it exists and ask whether to start from it or
from scratch.

Explore first so your questions are informed; then ask the user for what the data can't
say — in **one batched round**, not field-by-field across many turns. Build the YAML
**dynamically** from what you discover:

- **Inspect the HDF5** with `h5py`: open representative files; list groups/datasets,
  shapes, dtypes, and attributes (`visititems` walks objects, so a hard-linked field
  appears under one path only — use `visititems_links(print)` to see every path). Decide
  the **source** from how entities are packed (one
  file each → `files`; stacked on axis 0 → `batch`; one group each → `groups`; not HDF5 at
  all, with a sidecar table → `table`). When two of those fit at once — one entry per file
  whose signal also has a short frame axis, or a stack on axis 0 inside each of several
  groups — break the tie on **what a reader queries**: the unit they would search for is
  the entity, and an axis they would always want whole stays inside the artifact. Then the
  **artifacts** (the array datasets and good
  `type` names: spaces, dots, brackets and non-ASCII letters are fine, but not `/`, `?`,
  `#`, an ASCII control character or `%` with two hex digits, nor `.` or `..` alone, so
  keep a dataset's name where you can and replace only those; `optional: true` for one
  that some entities lack), the **parameters**
  (`params.group`, or `params.groups` when the scalars are spread over several groups —
  each nests under the name you give it; `from: attrs` when they are HDF5 attributes;
  `exclude` for blobs — an attribute's path is `<group path>/<name>`, e.g. `/operator_note` —
  and `recursive` for subgroups; a field named `uid` or `source_group`, and a
  `params.groups` name that is one of those, are refused — they are the two columns the
  manifest writes itself, so `exclude` the field, or nest its group under a name of your
  own to keep the value), and any **shared axes** (arrays
  *identical for every entity* → `shared:`, if you serve them at all — the YAML lists what
  the dataset serves, not what the file holds, so a constant placeholder nobody would read
  is simply left out; an axis that varies per entity is an artifact, and an array that is
  not an axis at all, a lookup or normalization table the whole dataset shares, belongs in
  `shared:` too). The entry names one copy by its absolute path, and `manifest` checks
  every copy the source holds against it: under `files`/`batch` that path in each file,
  under `groups` the same path inside **each entity group of each file**, so one file with
  four entity groups is checked four times. A differing copy is refused, naming both — you
  do not have to digest the arrays by hand first. A group that simply lacks the array is
  passed over, and its entity is served the copy the entry names.
  Field attributes (`units`, ...) are captured automatically — nothing to declare; an
  array attribute comes through as a list, and `docs/reference/manifest.md` says which
  values are left out and what a `batch` row's copy of them describes. A
  size-1 dataset (shape `(1,)`, as NeXus writes scalars) counts as a scalar, like 0-dim.
  So does a netCDF-4 dimension placeholder that has no coordinate variable (a dataset
  whose `NAME` attribute begins `This is a netCDF dimension`, value `0.0`): `exclude` it —
  and leave it out of `shared:` too, at any length, since a placeholder of 8 or 2 is
  identical in every file and would otherwise pass for an axis. A *real* coordinate
  variable of length 1 (its own `units`, a `NAME` that is just its name) is the opposite
  case: a genuine scalar parameter, and if it is identical in every file it hands every
  entity the same identity — take what varies from the name with `params.location`.
  Any bigger dataset in a params group, a `(7,)` array say, is skipped without a message
  under `files` and `groups` (in `batch`, a 1-D one of length N is one value per row); a
  per-entity log of that shape can still be an **artifact**, but it is then read and not
  queried, so ask the producer for a scalar summary (a mean, a range) if it must be
  searchable.
  Every container is judged on its own — each file, and under `groups` each entity group —
  again without a message: a field of size 1 in some of them and a bigger one in others is
  a parameter only where one of the rules above makes it one, and a `params.groups` group
  that some files or entity groups lack leaves those entities without its columns (with
  `from: attrs`, a missing group is an error naming the container). So check a field's
  shape, and a group's presence, across the containers, not in one.
  `path_<type>`, `dataset_<type>` and `index_<type>` are reserved for each artifact
  `type`, and `uid` and `source_group` always (`docs/reference/manifest.md`, Reserved
  names): a parameter with such a name goes
  in `exclude`, a `params.location` group gets another name, or pick artifact type names
  that do not clash. Every other name is free — `index`, `size` and `type` are ordinary
  parameters — so do not rename a producer's field out of caution.
- **netCDF-4 and CF files.** A packed variable (`scale_factor` / `add_offset` on an int
  array) registers as the **stored integers**: nothing unpacks, both factors ride along as
  artifact metadata, and a reader who does not apply them sees counts — say so in the
  `description`. A grid-mapping variable (a 0-dim value such as `crs = 0` whose
  meaning is entirely in its attributes) is broadcast to every entity as a meaningless
  parameter under `batch`: `exclude` it and put the projection in the dataset `metadata`.
  Dataset-level facts kept as root attributes (`@title`, `@source`) never reach `metadata`
  by themselves; copy the ones worth having into the YAML by hand. And a `.nc`, `.cdf` or
  `.grd` name is often netCDF-3 classic, which no HDF5 source can read: check the file
  signature before you plan anything (`docs/reference/errors.md`, the `file signature not
  found` row).
- **Many arrays side by side in one group (one dataset per channel or per step) → one
  `group` entry.** `{type: "trace_{name}", group: /channels}` gives one artifact per
  dataset directly in the group (subgroups are not members), typed with `{name}` filled
  in; quote the template. `members: "ch_*"` picks some, `optional: true` skips an entity
  without the group. Not under `batch` or `shared`. The types must stay unique after
  expansion. Count = matching members per entity. Thousands of per-step datasets
  register slowly: tell the user, and suggest stacking them into one array (or a `batch`
  file) before onboarding.
- **Decide identity.** The default hashes parameter values, so two entities with identical
  parameters would collide — `tilewright manifest` refuses that and names them. Repeated
  measurements (same settings, different runs) are the usual case: put a run number in the
  params, or write `identity: provenance` under the source. Say which and why in a comment.
  A `batch` file with no per-entity values at all takes `params: null` (identity becomes
  provenance), as `files` and `groups` do.
- **Values only in the file, directory or group name, or a batch row number →
  `params.location`.** A regex, in single quotes, searched in the path relative to
  `directory` (`groups`: `<file>:/<group>`; `batch`: `<file>:<row>`); each named group is
  a parameter and part of the identity:
  `params: {location: 'cell(?P<cell>\d+)/sweep_(?P<bias_mV>[+-]?\d+)mV\.h5$'}`. Digits
  become ints (leading zeros are lost), unnamed groups are wildcards. Try it with
  `re.search` on every name you listed: one that does not match stops the manifest. A
  `batch` file with nothing else per row can keep a queryable row number,
  `':(?P<shot>\d+)$'`, instead of `params: null`; with several files, capture part of the
  file name too, since every file's rows start again at 0.
- **Entities deeper than one group level, or values stored beside the entity groups →
  `groups` with a glob `entity_group`, `exclude_groups` and a params path that starts
  with `..`.** `entity_group: "/*"` makes every `/<site>/<detector>` an entity;
  `exclude_groups: [calibration]` leaves out a sibling group that is not one;
  `params: {groups: {calibration: ../calibration}}` reads it for each detector. Name
  each such group in its own path: `recursive: true` and a path that starts with `..`
  are a contract error in one params block. `params: {group: ..}` gives each entity its
  element of a 1-D array beside the groups whose length is the number of sibling groups,
  in sorted name order: check that the names are zero-padded (`scan_10` sorts before
  `scan_2`) and that the length matches after `exclude_groups`, or the array is skipped.
  When siblings read the same values, capture the group names with `params.location`.
  Entities that lack a parameter get null for it. Count = the subgroups of every
  matching group, less the excluded ones.
- **A `table` has no `identity` key: its `id` is the identity.** Check that the `id`
  column is unique (`df[col].is_unique`). If no single column is, list several,
  `id: [specimen, replicate]`, and say in a comment which rows needed the extra column. If no
  set of columns is unique (rows equal in every column), the table needs de-duplicating:
  that is the user's decision, so ask. Where two columns are both unique, prefer the one
  that **names the measurement** over one that encodes how the bytes are packed: the key a
  reader pastes should mean something, and a repacking must not re-key the dataset. A
  table serves no arrays at all, so arrays stacked beside it (a CSV whose column points
  into a pack) stay unserved — the choices are in `docs/explanation/sources.md`, "What a
  `table` can and cannot express", and they are the user's, so put them to them.
- **If groups carry an `NX_class` attribute, the file is NeXus — map it, don't guess:**
  one `NXentry` per file → `files` (several per file → `groups`); follow `@default` to the
  `NXdata` group — its `@signal` field, the `@axes` fields and any `FIELDNAME_errors` are
  the artifacts (axes go to `shared:` only if identical across the files you sampled; say
  which in a comment); `NXsample` / `NXinstrument` / `NXparameters` / `NXcollection` → one
  `params.groups` entry each, named after the group, with large string fields (JSON blobs)
  listed in `exclude`; root-level `definition` / `title` / `start_time` → a group entry
  pointing at the entry itself; `NXprocess` (`program`, `version`) → `producer` and a
  `code_version` key in `metadata`. Fields constant across every sampled file
  (`sample/chemical_formula`, `instrument/name`, `definition`) are candidates for dataset
  `metadata` — propose them as `# TODO confirm — "NiPS3" in all 12 files`, mapped onto
  `vocabulary.yml` ids. See `examples/datasets/files_nexus.yml` and
  `docs/explanation/nexus.md`. Two shapes that guide does not cover — a file with no
  `@default` anywhere, whose signal is marked on the field, and one entity spread over a
  header, a master and an image file — are in that page under "Files that do not follow
  the modern conventions".
- **Read the codebase / context** to infer metadata (`method`, `data_type`, `material`,
  `producer`, `project`, `facility`, `instrument`, `proposal`). Map each value onto a
  canonical id in `vocabulary.yml` where one fits, and where none does write the
  producer's own term: that is not inventing vocabulary, it registers as written with a
  warning, and the curator sees it later. What you must not do is coin an official-looking
  id, stretch an unrelated one, or edit `vocabulary.yml`. The facets the data rarely
  settles — `material` for something that is not a substance, `data_type` for observations,
  `producer` when a chain of codes made the files — are decided in the field descriptions
  in `contract.py`.

## Step 3 — Draft a first-pass YAML (don't blind-guess)

Write it as `<data root>/.tilewright/datasets/<KEY>.yml`, where `<KEY>` is `slug(label)`
(the YAML and its manifests travel with the data). Copy the `examples/datasets/<source>.yml`
that matches and fill it from what you found. Set `label`; leave `key` for
`tilewright manifest` to write. Keep the closed sections free of unknown keys — a typo
there is a hard error, reported in one sentence naming the field.

**Mark uncertainty as comments — do not silently guess.** If you can infer a value but it
was never stated explicitly, put your best guess in and flag it inline:

```yaml
metadata:
  method: [RIXS]          # TODO confirm — inferred from edrixs calls in sim.py, not stated
  material: NiPS3         # TODO confirm — guessed from output dir name
```

Leave fields you genuinely can't determine as `# TODO fill in` rather than fabricating
them. `material`, `producer`, `project`, `facility`, `contact` are almost never stated
inside the HDF5 — expect them to be blank until the user fills them in Step 4.

**Say who can confirm what.** `# TODO confirm` asks the data's owner a question they can
answer: what the material was, which code ran, who to contact. A fact you read out of the
files — a constant you promoted to a dataset key, a title written in a root attribute —
has no confirmer, and the owner will not recognize it. Mark those differently
(`# read from every file: @title = "..."`), say in the description that they come from the
files, and ask the user only whether they are worth keeping.

**Write a `description`**: one paragraph a reader uses to decide whether to open the
dataset. Repeat the defining numbers in it freely; every number in it must also exist as a
metadata key — the rule, and what counts as a number, are in the `description` field of
`contract.py`; nothing checks it, so it is yours to keep. Ask the user: *is there
anything a reader should know before trusting this data?* — a trust ceiling, a masked
region, a known artefact. That goes into the description, and any number in it becomes a
key the author names.

**Predict the counts now, from what you inspected**, and keep them. The formulas per
source are in `docs/reference/errors.md` under "Expected counts"; say how you got each
number ("5 files × `/spectra` leading axis 2000 = 10,000 entities; 1 artifact each + 2
shared axes"). These are what `tilewright manifest` will be checked against in Step 5.

## Step 4 — Hand it to the user for review (a dialogue, not a hand-off)

Show the drafted YAML **and your predicted counts**, and ask the user, in one message, the
concrete questions it leaves open: each `# TODO fill in`, each `# TODO confirm` (here's my
inference and why — right?), the `label` (it becomes the key, and on a shared server it
should carry the surname or group; show them the key it slugs to, since `slug()` keeps
A-Z and 0-9 only and an accented name comes out spelled with `_`), the `contact`, the
identity choice, and the
artifact/shared `type` names you chose. **Wait for their answers**, apply them, show the
result, and iterate until they say it's right. Only then move on. Never fill a blank from
anything other than the data or what the user told you.

**Run no `tilewright` command before this sign-off — `manifest` included.** It is local and
re-runnable, but it bakes the label into a key and snapshots the YAML into manifests, which
presents decisions the user hasn't made yet as settled.

## Step 5 — Manifest, compare — then stop

Once the user has signed off, from the data root:

```bash
tilewright manifest .tilewright/datasets/<KEY>.yml
```

It validates the contract, writes `key:` into the YAML, walks the files, and prints
`dataset=<KEY> entities=N artifacts=M shared=S`. Compare with your prediction from Step 4,
and **tell the user the result — then stop and wait for their go before registering.**

- **Match:** say so, with both numbers side by side, and that you are good to register
  (pending the two checks below, which you can do now and report in the same message).
- **Mismatch:** say so and **do not register.** A mismatch means you misread the data — the
  glob matched a stray file, the leading axis isn't what you thought, an entity group you
  didn't see. Go back to Step 2, find the discrepancy, fix the YAML, show the user the
  change, regenerate, compare again. A manifest you cannot account for does not get
  registered.
- **Collision error** (`N entities share K uids`): the data has repeated parameter sets,
  or a table repeats its id. Show the user the report (what differs for each uid) and its
  `Fix:` line; it is their call (Step 4 again).

Before reporting "good to register", two checks:

- **Where does the server run relative to the data?** Same filesystem → omit
  `server_base_dir`; mounts it elsewhere → set it; cannot see it at all →
  `tilewright register --upload` (trial with `-n 5`, verify, re-run). The rules —
  `readable_storage`, the physical-path caveat, what "the server's view" means — are
  **`docs/ONBOARDING.md` step 3**; follow that section rather than reasoning it out here,
  and **do not assume a host or facility**: the path the user gave you is where the data is.
- **Is the key already on the target server?** `list(from_uri(URL, api_key=KEY))`. If so,
  tell the user. `tilewright register` will compare fingerprints: the same data proceeds
  incrementally; different data under that label is refused with a message to choose
  another label. Which way to go is the user's decision, not yours.

## Step 6 — Register (on the user's go)

```bash
tilewright register .tilewright/datasets/<KEY>.yml --url <URL> --api-key <KEY>
```

(or `tilewright register --upload ...` — trial with `-n 5` first, verify, re-run without
`-n`; `TILED_URL` / `TILED_API_KEY` in the environment replace the flags). Above a few
thousand entities, tell the user how long the run will take *before* starting it: time
`-n 100` and multiply out (`docs/ONBOARDING.md` step 4, "How long a pointer run takes").
Read the summary
block, not the exit code: `Artifact errors` must be 0, `Broken nodes` must be absent, and
`Entities` + `Skipped` should equal the entity count from Step 5. Any
`WARNING ... half-registered` lines mean a previous run died mid-entity and this run
attached the rest — fine. A `Broken nodes` count means artifacts that are on the server
but serve nothing: each is named with its key, and the fix is `tilewright delete <KEY>
<ENTITY> <ARTIFACT>` for each, then register again.

## Step 7 — Verify: read it back (the gate that actually proves it)

Registration never opens the files: a pointer the server cannot follow registers with
`Artifact errors: 0` and fails only at first read. So the proof is a **read-back through
the server**, not the register summary. Run the read-back snippet in
**`docs/ONBOARDING.md` step 5** with the same URL and key you registered with.

Pass = the entity count matches, and one artifact array **and each shared axis** come back
with the shapes the manifest recorded, with a small slice read from one of them. Ask the
array client for `.shape`; never read `[:]` of a multi-gigabyte artifact to prove a
pointer works. A `table` has no array, so its pass is the entity count, one row's
metadata, and a `Key` search. Report those numbers. A bare `500` on the read is
the path/adapter/allowlist problem — `docs/reference/errors.md` decodes it, and every
other failure you are likely to meet, by symptom; fix the YAML, regenerate,
**delete the dataset** (`docs/ONBOARDING.md` step 6), re-register — an existing artifact
is never rewritten. A metadata-only correction needs no delete: edit the YAML and run
`tilewright register --update`.

## Guardrails

- **Two sources only: the data, and what the user tells you.** Never mine the repo or git
  history for a dataset's metadata. If in doubt, ask the user.
- **It's a conversation, with two stops.** Ask for starting context and wait (Step 1);
  explore; ask the open questions in one batched round and wait (Step 4) — run **no
  `tilewright` command** until the user has signed off on the YAML. After `manifest`,
  report the count comparison and wait again (Step 5) — run **no `tilewright register`**
  until they say go.
- **Predict, then compare.** A mismatch means you misread the data — don't register, find
  out why.
- **The read-back is the proof.** `register` reporting zero errors proves nothing about
  whether the server can read a byte; Step 7's read of an artifact and each shared axis
  does. Report what came back.
- **Check the server before registering.** If the key already exists there, that's a
  decision for the user (new label / continue / update), not for you.
- Build the YAML **dynamically** from exploring the data + code, then have the user review
  it — don't interrogate them field-by-field, and don't wait for a full spec before drafting.
- **Do not blind-guess.** Inferred-but-unstated values go in as a best guess with a
  `# TODO confirm` comment saying what you inferred it from; undeterminable fields stay
  `# TODO fill in`.
- Four sources only — if the data fits none, the producer reshapes it; do not invent one.
- Vocabulary is soft: unknown values warn, they do not block. Don't hard-reject, don't
  invent ids, and never edit `vocabulary.yml` during onboarding (that is the
  `vocab-review` skill's job, by pull request).
