# How to install

!!! info "Only want to read a catalog?"

    You do not need this package. The catalog is served over HTTP and Tiled's own
    client does all the work: `pip install 'tiled[client]'`, then see
    [How to read a registered catalog](using-the-catalog.md).

Everything below is for **publishing** data. It runs the `tilewright` command line, so it
wants a clone of the repository and **Python 3.11 or newer**. The same install serves both
transports, pointer registration and `--upload`; which one you use is chosen at
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
