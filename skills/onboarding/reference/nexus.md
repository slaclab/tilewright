# NeXus

**Read this when** any group carries an `NX_class` attribute (Step 2): the file is NeXus,
so map it with the conventions below rather than guessing. See
`../examples/files_nexus.yml` for a complete example.

TileWright does not implement NeXus classes. Its generic contract can describe
NeXus-structured HDF5, and this page maps between them.

## How NeXus concepts map

| NeXus need | Contract feature | Catalog result |
|---|---|---|
| Scalars in several groups | `params.groups` | Nested, queryable entity metadata |
| Scalars written as length-1 arrays, shape `(1,)` | Automatic: read like 0-dim scalars | Scalar metadata, strings decoded |
| Nested groups such as `NXdetector` | `params.recursive: true` | Deeper nested metadata |
| Collections containing unwanted datasets | `params.exclude` | Selected paths are skipped |
| Attributes on scalar fields | Automatic capture | Labels such as `instrument.Ei_units` |
| Attributes on arrays | Automatic capture | Metadata on the artifact node |
| Several `NXentry` groups per file | `groups` source | One entity per entry |
| Repeated runs with identical settings | `identity: provenance` | One entity per file, never a collision |
| HDF5 soft or external links | h5py resolves the link; *below* the params group, `recursive: true` follows only what stays inside it ([`recursive`](dataset-yaml.md#params)) | The configured path is recorded |

Map a tree using these conventions:

```text
NXroot@default -> entry                 one NXentry per file -> files
                                         several per file -> groups
NXentry@default -> data
  NXdata signal, axes, and errors       -> artifacts
                                         identical axes -> shared
  NXinstrument, NXsample,
  NXparameters, NXcollection            -> params.groups
  definition, title, start_time         -> metadata.entry.*
  NXprocess program and version         -> metadata.producer, metadata.code_version
  values constant across files          -> dataset metadata, after user review
```

In practice:

- **Entities.** One `NXentry` per file → `files`; several per file → `groups`.
- **Artifacts.** Follow `@default` to the `NXdata` group: its `@signal` field, the `@axes`
  fields and any `FIELDNAME_errors` are the artifacts. Axes go to `shared:` only if
  identical across the files you sampled; say which in a comment.
- **Parameters.** `NXsample` / `NXinstrument` / `NXparameters` / `NXcollection` → one
  `params.groups` entry each, named after the group, with large string fields (JSON blobs)
  listed in `exclude`. Root-level `definition` / `title` / `start_time` → a group entry
  pointing at the entry itself.
- **Metadata.** `NXprocess` (`program`, `version`) → `producer` and a `code_version` key.
  Fields constant across every sampled file (`sample/chemical_formula`, `instrument/name`,
  `definition`) are candidates for dataset `metadata`: propose them, mapped onto vocabulary
  ids, marked as read from the files (`# read from all 12 files: "NiPS3"`), for the owner to
  keep or drop.

For `params.groups`, names become metadata prefixes. A field `Ei` in the group named
`instrument` becomes `instrument.Ei`, which Tiled can query with
`Key("instrument.Ei") > 50`.

Nothing in this mapping names a NeXus class. A plain HDF5 file with scalars in
`/settings/` and `/sample/` receives the same treatment.

## Files that do not follow the modern conventions

The mapping above assumes `@default` attributes and a group-level `@signal`. Two shapes
common in published files do not have them.

**The signal is marked on the field.** Older writers set no `@default` anywhere and mark
the signal on the dataset instead: `<field>@signal = "1"`, with `<field>@axes` a single
colon-separated string of the axis field names, `"frame:row:column"`. Read the
group's datasets, take the one whose own `signal` attribute is set as the artifact, and
split its `axes` string on `:` for the axis fields. Nothing in TileWright reads either
convention — the YAML names HDF5 paths — so the file registers exactly as a modern one
does once you have found the paths.

**One entity, several files.** A header file, a master file and image files joined by
external links and a virtual dataset are one measurement. Make the **file the `pattern`
matches** the entity — the one from which every path resolves, usually the header — and
write the artifact and params paths as that file sees them: h5py follows an external link
when `tilewright manifest` scans, so a sibling file's group can be a `params.groups` entry
like any other. Two things to check:

- **Only the matched file is stamped.** `file_size` and `file_mtime` describe it alone, so
  a regenerated image file is not reported as
  [changed on disk](manifest.md#snapshot-semantics).
- **A virtual dataset has its own dtype.** It can be narrower than the sources it maps
  (a `uint16` layout over `uint32` images clips every value above 65535), and that dtype is
  what the manifest records and every read returns. `dset.is_virtual` and
  `dset.virtual_sources()` show what a signal is really made of.

## Deliberate boundaries

- **`NXdata` is not a catalog container.** Its signal, axes, and error arrays are sibling
  artifacts. Preserving their formal linkage is deferred until Tiled's own node
  relationships land; a private convention now would have to be unwound then.
- **Application definitions are not validated.** `definition` is captured as metadata,
  but nothing checks the file against `NXsqom` or any other definition.
- **Units remain labels.** `Ei_units` is stored; nothing converts or validates units.

For exact field behavior, see [the dataset YAML reference](dataset-yaml.md)
and [the manifest reference](manifest.md).

## Background

**Why the contract grew.** A SEQUOIA S(Q,E) dataset exposed two gaps. Its entity parameters were spread across
`NXinstrument`, `NXcollection`, and `NXsample`, while the contract could name only one
parameter group. Its `NXdata` arrays also carried relationships and units that disappeared
when registered as independent artifacts.

Requiring users to restructure valid NeXus files would make onboarding harder. Hard-coding
NeXus classes would undermine the dataset-agnostic design. The contract therefore gained
generic ways to preserve the useful structure.
