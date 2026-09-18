# How to install

!!! info "Only want to read a catalog?"

    You do not need this package. The catalog is served over HTTP and Tiled's own
    client does all the work: `pip install 'tiled[client]'`, then see
    [How to read a registered catalog](using-the-catalog.md).

Everything below is for **publishing** data. It runs the `tilewright` command line, so it
wants the package installed and **Python 3.11 or newer**. A clone is the fullest way and
the one the three tabs below take; the whole pipeline also runs from an install with no
checkout at all ([No checkout](#no-checkout)). The same install serves both transports,
pointer registration and `--upload`; which one you use is chosen at
[step 4 of the publishing guide](ONBOARDING.md#4-register-the-dataset).

## 1. Install

=== "uv"

    ```bash
    git clone https://github.com/slaclab/TileWright
    cd TileWright
    uv run tilewright --help
    ```

    There is no separate install step: `uv run` builds `.venv` from the checked-in
    `uv.lock` the first time it is used. Prefix commands with `uv run`, or
    `source .venv/bin/activate` once and drop the prefix. Tools that are not part of the
    package (pytest, marimo, mkdocs) are pulled in per command with `--with`.

=== "pip"

    ```bash
    git clone https://github.com/slaclab/TileWright
    cd TileWright
    python3 -m venv .venv && source .venv/bin/activate
    pip install -e ".[test]"
    tilewright --help
    ```

    For conda or mamba, swap the `venv` line for
    `conda create -n tilewright python=3.12 -y && conda activate tilewright`.

=== "pixi"

    ```bash
    git clone https://github.com/slaclab/TileWright
    cd TileWright
    pixi init --import pyproject.toml   # once; writes pixi.toml from the project table
    pixi shell
    pip install -e .
    tilewright --help
    ```

    Installing pixi itself: <https://pixi.prefix.dev/latest/installation/>.

`tilewright --help` printing its three commands is the check. For a fuller one,
`uv run --extra test pytest` (plain `pytest` in an activated environment) needs no server
and no credentials.

### No checkout

The package installs straight from the repository URL, into a tool environment of its own
or into an environment you already have:

```bash
uv tool install git+https://github.com/slaclab/TileWright   # its own environment, on PATH
pip install git+https://github.com/slaclab/TileWright       # or into the active one
tilewright --help
```

Nothing downstream needs a checkout: `manifest`, `register` (both transports) and `delete`
all run, and so does reading the catalog back. Four things live in the repository rather
than in the package, so an install without one does without them:

| Only in a checkout | What to do instead |
|---|---|
| `examples/datasets/*.yml`, one annotated starting YAML per source tag | Write the YAML from the skeleton and the field tables in [the dataset YAML reference](reference/dataset-yaml.md), or read the examples [in the repository](https://github.com/slaclab/TileWright/tree/main/examples/datasets) |
| the `/onboarding` skill for Claude Code | Author by hand: [step 1 of the publishing guide](ONBOARDING.md#by-hand) |
| `examples/notebook.py`, the marimo tour of the read path | Read the catalog with the snippets in [How to read a registered catalog](using-the-catalog.md); the notebook is one self-contained file, so saving it [from the repository](https://github.com/slaclab/TileWright/blob/main/examples/notebook.py) and running it as that page describes also works |
| the test suite | `tilewright --help`, then `tilewright manifest --check MY_DATASET.yml`, which validates and prints the key without touching the network |

The vocabulary is **not** one of them: `vocabulary.yml` ships inside the package, so its
canonical ids are readable wherever `tilewright` is installed.

```bash
python -c "import tilewright, pathlib; print(pathlib.Path(tilewright.__file__).parent / 'vocabulary.yml')"
```

## 2. Point at a server

--8<-- "connect.md"

!!! warning "Uploading reads your files locally"

    `tilewright register --upload` opens the HDF5 files on the machine it runs on. If your
    data is on a cluster, either install and run there, or copy a subset down first.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `tilewright: command not found` | The environment is not active: `source .venv/bin/activate`, `pixi shell`, or `conda activate`. With uv, prefix commands with `uv run` |
| `requires-python >= 3.11` | The environment is older than the package supports. `uv venv --python 3.12`, or recreate the conda environment |
| `ensurepip is not available` | Your distribution ships `venv` separately (`apt install python3-venv`), or use `uv venv` |
| `ModuleNotFoundError: tilewright` | The package was installed into a different environment than the one you are in, or `pip install -e .` was run outside the checkout |

---

Next: [How to publish a dataset](ONBOARDING.md).
