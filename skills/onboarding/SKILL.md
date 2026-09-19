---
name: onboarding
description: >-
  Onboard an HDF5 (or netCDF-4, NeXus) dataset into a Tiled catalog with tilewright:
  explore the files, draft the dataset YAML with the user, predict and check the counts,
  register, and read it back through the server. Use when the user wants to onboard,
  register, publish or add a dataset to Tiled, write a tilewright dataset YAML, or asks
  to "get ready to onboard a dataset".
---

# Onboarding a dataset

Goal: take a producer's HDF5 dataset and register it into the catalog by authoring **one
dataset YAML** against the contract, then running `tilewright manifest` and
`tilewright register`. You onboard by reading the *contract*, never the implementation.

## Where you are

The session runs in the user's **data root**, where the YAML and its manifests go. If
your shell is not on the host that holds the data (a login node, a laptop over a bridge),
run every command — `h5py`, `tilewright` — on that host, not beside you. What
this skill reads ships beside this file: `reference/` and `examples/`. Every `reference/…`
and `examples/…` path below is relative to this skill's directory, `$SKILL`, not to the
working directory. The contract models and the vocabulary ship in the package, `<pkg>`,
which this skill sits inside once installed:

```bash
SKILL=~/.claude/skills/onboarding        # the base directory Claude Code printed when this
                                         # skill loaded; if it printed none (you opened the
                                         # file by path), the directory of that SKILL.md
d=$(readlink -f "$SKILL/../..")          # the package, or a checkout's root
PKG=$([ -f "$d/contract.py" ] && echo "$d" || echo "$d/src/tilewright")
ls "$PKG/contract.py" "$PKG/vocabulary.yml"
```

If `tilewright` is not on `PATH`, stop and ask the user to install it
(`tilewright skills install` is how this skill got here).

## Step 0 — Read the contract (do this first)

Read these now. They define what a valid dataset is; do not reverse-engineer it from
`manifest.py` / `register.py`:

1. `<pkg>/contract.py` — the authoritative field contract: every YAML field, its type,
   whether it is required, and what it means. Its descriptions settle the hard cases.
2. `reference/walkthrough.md`, the whole page (it is short) — the path from YAML to
   read-back that the steps below follow.

Everything else is read when its moment comes, one page per decision:

| Read | When |
|---|---|
| `reference/paths-and-server.md` | Step 1, once the user says where the server runs; again in Step 5 |
| `reference/source-and-entity.md` | Step 2, before anything else |
| `examples/<source>.yml` | Step 2, once you know the source (`files_nexus.yml` for NeXus) |
| `reference/params-and-identity.md` | Step 2, parameters and identity |
| `reference/artifacts-and-shared.md` | Step 2, artifacts and shared axes |
| `reference/nexus.md` | Step 2, if any group has an `NX_class` attribute |
| `reference/netcdf-cf.md` | Step 2, for a `.nc`/`.cdf`/`.grd` name, or CF attributes (`NAME`, `scale_factor`, `_FillValue`) in any HDF5 file |
| `reference/metadata-and-vocabulary.md` and `<pkg>/vocabulary.yml` | Step 2, drafting `metadata` |
| `reference/counts-and-cost.md` | Step 3, predicting the counts |
| `reference/troubleshooting.md` | whenever a command fails |
| `reference/dataset-yaml.md`, `reference/manifest.md` | to look up one field or one manifest column |

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
  server can't see the files → `tilewright register --upload`;
  `reference/paths-and-server.md`); and
- any other context they want to give (paper, README, prior YAML, etc.).

**This is a conversation — stop and wait for the answer**, even if the data path was
already given in the invocation. What the user tells you here is the *only* source of
metadata besides the data itself (see Step 2). Don't go looking for more on your own.

## Step 2 — Explore the data and codebase

Explore **only two things**: (a) the data path, and (b) the codebase/context the user
named in Step 1. Do **not** hunt for context elsewhere in the repo or its history — not the
`examples/` beyond using them as templates, not deleted files showing in `git status`, not
`git show`/`git log`, not `config.yml`'s storage roots, not example keys in
`README.md`/`CLAUDE.md`, not old manifests. Those describe *other* datasets and
deployments; copying values from them fabricates provenance for this one. If you notice
such a file, ignore it and — if it seems relevant — *mention* it to the user and let them
decide whether to hand it to you.

The same goes for a YAML that already describes **this very dataset** (a prior
`.tilewright/datasets/<KEY>.yml` in the data root, or manifests for it): don't silently
adopt, overwrite, or delete it. Tell the user it exists and ask whether to start from it or
from scratch.

Explore first so your questions are informed; then ask the user for what the data can't
say — in **one batched round**, not field-by-field across many turns. Work through these in
order, reading each page when you reach it:

1. **Inspect across the containers, not one file.** Dump representative files with
   `visititems_links`, then compare paths, shapes, dtypes and attributes across every file
   (and every entity group). Differences are silent later.
   → `reference/source-and-entity.md`, "Inspect across the containers"
2. **Choose the source and the entity.** How the entities are packed decides `files`,
   `batch`, `groups` or `table`; a path that varies per file means `groups`; files that
   split one acquisition are pieces of one array, not entities; state what a reader's usual
   read costs, and let it break a tie.
   Archives (zip, tar) and formats other than HDF5 are extracted or converted first.
   → `reference/source-and-entity.md`
3. **Artifacts and shared axes.** Which arrays each entity serves, their `type` names,
   which are `optional`, which are identical for every entity, and what does not travel
   with them (a parent group's attributes, attribute-only records). Siblings with one shape
   and ordered names are a series stored as pieces: tell the owner what reading it costs,
   whatever the count.
   → `reference/artifacts-and-shared.md`
4. **Parameters and identity.** Which scalars become queryable parameters, the names the
   manifest keeps for itself, values only in a name (`params.location`), and how each
   entity stays distinct. Decide identity now, and say why in a comment.
   → `reference/params-and-identity.md`
5. **Formats.** NeXus → `reference/nexus.md`; netCDF or CF → `reference/netcdf-cf.md`
   (check the file signature first).
6. **Metadata, from the user and the codebase only.** Nothing fills `metadata` in from the
   files; map values onto vocabulary ids, and read the field in `contract.py` for the hard
   cases. → `reference/metadata-and-vocabulary.md`

## Step 3 — Draft a first-pass YAML (don't blind-guess)

Write it as `<data root>/.tilewright/datasets/<KEY>.yml`, where `<KEY>` is `slug(label)`
(the YAML and its manifests travel with the data). Copy the `examples/<source>.yml`
that matches, **delete its `key:` line** (it is the example's key, and `tilewright
manifest` writes yours from the label), and fill it from what you found. Set `label`.
Keep the closed sections free of unknown keys — a typo there is a hard error, reported in
one sentence naming the field.

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

**Predict the counts now, from what you inspected**, and keep them: entities, artifacts
per entity, shared axes, with how you got each (`reference/counts-and-cost.md`). These are
what `tilewright manifest` will be checked against in Step 5.

**Check the cost.** When the nodes you predict pass the threshold in
`reference/counts-and-cost.md`, "When the source's shape is the problem", or you found a
series stored as pieces or an acquisition split across files, raise it with the user in Step 4, with the node count, a rough
time and the choices on that page. The choice is theirs, before sign-off.

## Step 4 — Hand it to the user for review (a dialogue, not a hand-off)

Show the drafted YAML **and your predicted counts**, and ask the user, in one message, the
concrete questions it leaves open: each `# TODO fill in`, each `# TODO confirm` (here's my
inference and why — right?), the `label` (it becomes the key, and on a shared server it
should carry the surname or group; show them the key it slugs to, since `slug()` keeps
A-Z and 0-9 only and an accented name comes out spelled with `_` — the choices when that
spelling will not do are in `reference/walkthrough.md`, step 1), the `contact`, the
identity choice, and the
artifact/shared `type` names you chose. **Wait for their answers**, apply them, show the
result, and iterate until they say it's right. Only then move on. Never fill a blank from
anything other than the data or what the user told you.

**Write nothing before this sign-off: no `tilewright manifest`, no `register`.** `manifest`
is local and re-runnable, but it bakes the label into a key and snapshots the YAML into
manifests, which presents decisions the user hasn't made yet as settled.
`tilewright manifest --check` is the exception, and the tool for this step: it validates
the contract and prints the key the label slugs to, and writes nothing — neither the `key:`
line nor a manifest (`tilewright manifest --help`). Run it to show the
user the key, as `reference/walkthrough.md` step 1 says.

## Step 5 — Manifest, compare — then stop

Once the user has signed off, from the data root:

```bash
tilewright manifest .tilewright/datasets/<KEY>.yml
```

It validates the contract, writes `key:` into the YAML, walks the files, and prints
`dataset=<KEY> entities=N artifacts=M shared=S`. Compare with your prediction from Step 3,
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
  `readable_storage`, the physical-path caveat, the server's config — are
  **`reference/paths-and-server.md`**; follow that page rather than reasoning it out here,
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
`-n`; `TILED_URL` / `TILED_API_KEY` in the environment replace the flags). For any run
longer than a few minutes, tell the user how long it will take *before* starting it: time
`-n 100` and multiply out (`reference/counts-and-cost.md`).
Read the summary
block, not the exit code: `Artifact errors` must be 0, `Broken nodes` must be absent, and
`Entities` + `Skipped` should equal the entity count from Step 5. The summary counts this
run only: after a `-n` sample, the full run reports the sample's entities as `Skipped`. Any
`WARNING ... half-registered` lines mean a previous run died mid-entity and this run
attached the rest — fine. A `Broken nodes` count means artifacts that are on the server
but serve nothing: each is named with its key, and the fix is `tilewright delete <KEY>
<ENTITY> <ARTIFACT>` for each, then register again.

## Step 7 — Verify: read it back (the gate that actually proves it)

Registration never opens the files: a pointer the server cannot follow registers with
`Artifact errors: 0` and fails only at first read. So the proof is a **read-back through
the server**, not the register summary. Run the read-back snippet in
**`reference/walkthrough.md` step 5** with the same URL and key you registered with.

Pass = the entity count matches, and one artifact array **and each shared axis** come back
with the shapes the manifest recorded, with a small slice read from one of them; step 5
also says how to check the values against the file. Ask the
array client for `.shape`; never read `[:]` of a multi-gigabyte artifact to prove a
pointer works. A `table` has no array, so its pass is the entity count, one row's
metadata, and a `Key` search. Report those numbers. A bare `500` on the read is
the path/adapter/allowlist problem — `reference/troubleshooting.md` decodes it, and
[the operator errors page](https://github.com/slaclab/tilewright/blob/main/docs/reference/errors.md) every other failure after
`manifest`, by symptom; fix the YAML, regenerate,
**delete the dataset** (`reference/walkthrough.md` step 6), re-register — an existing artifact
is never rewritten. A metadata-only correction needs no delete: edit the YAML and run
`tilewright register --update`.

## Guardrails

- **Two sources only: the data, and what the user tells you.** Never mine the repo or git
  history for a dataset's metadata. If in doubt, ask the user.
- **It's a conversation, with two stops.** Ask for starting context and wait (Step 1);
  explore; ask the open questions in one batched round and wait (Step 4) — **write
  nothing** until the user has signed off on the YAML; `tilewright manifest --check`, which
  writes nothing, is the one command that belongs before the sign-off (Step 4). After
  `manifest`, report the count comparison and wait again (Step 5) — run **no
  `tilewright register`** until they say go.
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
