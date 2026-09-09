# NeXus support

TileWright does not implement NeXus classes. Its generic contract can describe
NeXus-structured HDF5, and the onboarding skill knows how to map between them. See
`examples/datasets/files_nexus.yml` for a complete example.

## Why the contract grew

A SEQUOIA S(Q,E) dataset exposed two gaps. Its entity parameters were spread across
`NXinstrument`, `NXcollection`, and `NXsample`, while the contract could name only one
parameter group. Its `NXdata` arrays also carried relationships and units that disappeared
when registered as independent artifacts.

Requiring users to restructure valid NeXus files would make onboarding harder. Hard-coding
NeXus classes would undermine the dataset-agnostic design. The contract therefore gained
generic ways to preserve the useful structure.

## How NeXus concepts map

| NeXus need | Contract feature | Catalog result |
|---|---|---|
| Scalars in several groups | `params.groups` | Nested, queryable entity metadata |
| Nested groups such as `NXdetector` | `params.recursive: true` | Deeper nested metadata |
| Collections containing unwanted datasets | `params.exclude` | Selected paths are skipped |
| Attributes on scalar fields | Automatic capture | Labels such as `instrument.Ei_units` |
| Attributes on arrays | Automatic capture | Metadata on the artifact node |
| Several `NXentry` groups per file | `groups` source | One entity per entry |
| Repeated runs with identical settings | `identity: provenance` | One entity per file, never a collision |
| HDF5 soft or external links | h5py resolves the link | The configured path is recorded |

The onboarding skill maps a tree using these conventions:

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

For `params.groups`, names become metadata prefixes. A field `Ei` in the group named
`instrument` becomes `instrument.Ei`, which Tiled can query with
`Key("instrument.Ei") > 50`.

Nothing in this mapping names a NeXus class. A plain HDF5 file with scalars in
`/settings/` and `/sample/` receives the same treatment.

## Deliberate boundaries

- **`NXdata` is not a catalog container.** Its signal, axes, and error arrays are sibling
  artifacts. Preserving their formal linkage is deferred until Tiled's own node
  relationships land; a private convention now would have to be unwound then.
- **Application definitions are not validated.** `definition` is captured as metadata,
  but nothing checks the file against `NXsqom` or any other definition.
- **Units remain labels.** `Ei_units` is stored; nothing converts or validates units.

For exact field behavior, see [the dataset YAML reference](../reference/dataset-yaml.md)
and [the manifest reference](../reference/manifest.md). To register a real dataset, follow
[How to publish a dataset](../ONBOARDING.md).
