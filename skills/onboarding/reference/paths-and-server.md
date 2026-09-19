# Paths and the server

**Read this when** the owner tells you where the Tiled server runs relative to the data
(Step 1), and again before registering (Step 5): which transport to use, and how the
YAML's paths and the server's config must agree.

## Pick a transport

This decision changes two fields of the YAML and one step of registering; everything else
is the same either way.

| | The server reads your files | You upload the arrays |
|---|---|---|
| **Command** | `tilewright register` | `tilewright register --upload` |
| **Use when** | The data is on a filesystem the Tiled server can open, the normal case for facility storage | The server cannot see your disk: a laptop, another institution |
| **What is registered** | Pointers. No array bytes move | The arrays themselves, streamed into the server's storage |
| **Afterwards** | The files stay where they are, and stay load-bearing | The server owns the bytes; your local files are no longer involved |

A dataset is one transport or the other; `tilewright register` refuses to mix them. Do not
assume a host or facility: the path the owner gave you is where the data is.

## When you upload the arrays

`directory` is the path on **your** machine, where `--upload` reads from. Omit
`server_base_dir`; the server never opens your files, so no path has to agree with
anything and the stock Tiled adapter serves the uploaded arrays.

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

The receiving server needs `writable_storage`; see
[How to host a server](https://github.com/slaclab/tilewright/blob/main/docs/host-a-server.md).

## When the server reads the files

`directory` is the root as **you** see it; `server_base_dir` is the same root as **the
server** sees it. Three settings have to describe the same bytes:

![Two of the three are in your dataset YAML; the third is the server's own config.](diagrams/paths.svg)

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
- A file that is itself a virtual dataset (detector master files often are) is read through
  its source files every time. They must be readable where the server looks too, or the
  array reads as its fill value with no error; the read-back compares a member with the
  original ([when the source's shape is the problem](counts-and-cost.md#when-the-sources-shape-is-the-problem)).

### The server's config

The server also needs TileWright's array adapter, or every read returns HTTP 500 after a
registration that looked fine. [`config-pointer.yml`](config-pointer.yml), beside this
page, is a complete config for a server that serves pointer registrations, with the
adapter line: set `readable_storage` to your server-side root and start it with
`tiled serve config config-pointer.yml --api-key <KEY>`. Running a shared server is in
[How to host a server](https://github.com/slaclab/tilewright/blob/main/docs/host-a-server.md).
