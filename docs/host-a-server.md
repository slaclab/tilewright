# How to host a server

Most people register into a server someone else runs and never need this page. It is for
the operator, or for anyone who wants a local server to test against before touching a
shared one.

## Which server

Two configs ship with the repository. Both are Tiled's own format; nothing here is a
TileWright setting except the one adapter line.

| | `config.yml` | `config.upload.yml` |
|---|---|---|
| **Serves** | pointer registrations: the server opens registrants' HDF5 files | uploaded arrays: the server stores bytes registrants stream in |
| **Needs** | `adapters_by_mimetype` and a `readable_storage` allowlist | `writable_storage` |
| **Listens on** | `127.0.0.1:8005` | `0.0.0.0:8005`, for remote registrants |

Start either from the repository root:

```bash
uv run --with 'tiled[server]' tiled serve config config.yml --api-key <KEY>
```

The key you pass is the one registrants use. For per-person keys with expiry, log in as an
admin and mint them; `scripts/mint_api_keys.py` does that in bulk.

## A whole pointer-serving config

This is a whole file, not an excerpt: it is Tiled's own config format, and the
repository's `config.yml` is this same shape with the operator's own storage roots. Only
the adapter line is TileWright's.

```yaml title="config.yml"
--8<-- "config-pointer.yml"
```

Both settings sit inside a tree's `args`, not at the top level — that is the part people
write from memory and get wrong. `uri` names the catalog database (`sqlite:///catalog.db`
is a file in the directory the server starts from; a shared deployment points it at
PostgreSQL), `init_if_not_exists` creates it on the first run, and `uvicorn` is where the
host and port go. A server that also accepts `--upload` registrations adds
`writable_storage` beside them, as `config.upload.yml` does.

The adapter line makes the server slice batched arrays in h5py instead of materializing
whole datasets ([sliced reads](explanation/data-model.md#an-entity-is-a-slice)). It is an import path
resolved inside the server, so `tilewright` must be installed in the server's
environment. Without it, `tilewright register` succeeds and every read returns HTTP 500.

`readable_storage` lists the roots the server may open, as **it** sees them. A registration
whose `server_base_dir` (or `directory`) is outside every root also succeeds and also
fails on read, with `Refusing to serve file://...` in the server log. The check compares
paths as written and never resolves symlinks, so list physical paths.

## Is the server you are talking to yours?

Four signals lie: a `curl` that gets a reply proves *a* server is up, not yours; uvicorn
prints `Application startup complete` before it binds; a `catalog.db` on disk may belong
to an older run; a stale log looks live. What does not lie is the process behind the port:

```bash
ss -ltnp 'sport = :8005'                 # the pid listening on the port
readlink /proc/<pid>/cwd                 # the directory it was started from
pwd -P                                   # must be the same
```

If the pid is not yours, someone else's server answers on that port and your
registrations go into their catalog. Pick another port.

## Deleting what registrants uploaded

`tilewright delete <KEY>` on an uploaded dataset removes the array bytes under
`writable_storage` as well as the catalog entries; there is no other copy. On a pointer
dataset it removes only catalog entries. Every attendee key that carries `delete:node`
can delete any container, so on a shared server either withhold that scope or say so.
