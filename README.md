# TileWright

Register scientific HDF5 datasets into a [Tiled](https://blueskyproject.io/tiled/)
catalog from one YAML contract, then find them by their physics and read them from
anywhere. Your data keeps the names and the files it already has.

```bash
tilewright manifest .tilewright/datasets/MY_DATASET.yml     # validate, derive the key, scan the files
tilewright register .tilewright/datasets/MY_DATASET.yml     # publish into a running server
```

```python
from tiled.client import from_uri
from tiled.queries import Key

c = from_uri(URL, api_key=KEY)
hits = c["MY_DATASET"].search(Key("sigma") >= 0.04)
hits.values().first()["rixs_spectrum"][:]        # (151, 40), sliced server-side
```

Every dataset registers as the same three levels, Dataset → Entity → Artifact, with the
entity's parameters as queryable metadata and its arrays served lazily. One YAML says
where the entities come from (`files`, `batch`, `groups` or `table`), what arrays they
carry, and the facets a reader searches by. Nothing about your science is hardcoded.

**Documentation:** <https://slaclab.github.io/tilewright/>

- [Install](docs/install.md) (Python ≥ 3.11, `uv run tilewright --help`)
- [Publish a dataset](docs/ONBOARDING.md), with an agent or by hand
- [Read a registered catalog](docs/using-the-catalog.md), which needs only `tiled[client]`
- [Host a server](docs/host-a-server.md)
- [The YAML contract](docs/reference/dataset-yaml.md), generated from `src/tilewright/contract.py`

**Automatic ingestion** for AmSC lives in
[slaclab/amsc-catalog-publisher](https://github.com/slaclab/amsc-catalog-publisher).

## Repository

```
src/tilewright/      the package: contract, vocabulary, manifest, register, delete, client, adapter
examples/datasets/   one annotated YAML per source tag, with expected counts
examples/notebook.py marimo tour of the read path
docs/                the site (mkdocs-material); docs/adr/ is internal
scripts/             maintainer tools; see CONTRIBUTING.md
.claude/skills/      onboarding (for producers) and vocab-review (for maintainers)
config.yml           a local pointer-serving server; config.upload.yml hosts uploads
```

`uv run --extra test pytest` runs the offline suite; `-m integration` needs a server.
Contributing, the one-fact-one-home documentation rule, and how to add a vocabulary term:
[CONTRIBUTING.md](CONTRIBUTING.md).

TileWright continues [carbonscott/tiled-catalog-broker](https://github.com/carbonscott/tiled-catalog-broker)
and draws on [carbonscott/tilewright](https://github.com/carbonscott/tilewright); see
`docs/adr/0005-tilewright-lineage.md`. Apache-2.0.
