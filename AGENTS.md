## Environment

Use `uv` (`uv run tilewright ...`, `uv run --extra test pytest`). Nothing in this repo
assumes a machine or facility: it runs from any checkout with `uv`, and `config.yml`
serves data placed under `./data/` with no edits. Python ≥ 3.11.

## What this is

**TileWright** registers multi-entity scientific HDF5 datasets into a
[Tiled](https://blueskyproject.io/tiled/) catalog from one YAML contract.

Hierarchy: **Dataset → Entity → Artifact**, three nested Tiled containers. Datasets carry
facets (`method`, `material`, `producer`, `contact`, `description`, ...); entities carry
their physics parameters as queryable metadata; artifacts are array children. Keys are
readable: `client["BROAD_SIGMA"][entity_key]["rixs_spectrum"]`.

Pipeline: author YAML → `tilewright manifest` (validate, write `key`, scan, Parquet) →
`tilewright register` (HTTP, pointer or `--upload`) → read back. The Parquet manifest is
the contract between the two commands: no parameter name, artifact type, or file layout
is hardcoded anywhere.

Two read paths: through the server (the default, the only one for uploads) and straight
from the files via the `path_/dataset_/index_` locators (`tilewright.client`).

## Language

The domain language is in `CONTEXT.md`. Use *source* (not layout), *manifest* (not
generate), *identity* and *fingerprint* as defined there. "Mode A/B" is retired.

## Contract surface vs implementation

An agent onboards a dataset by reading the **contract surface** only: `contract.py`,
`vocabulary.yml`, `examples/datasets/*.yml`, `docs/ONBOARDING.md`,
`docs/reference/errors.md`. Needing to read `manifest.py` or `register.py` to learn what
a valid YAML is means the surface has a gap; fix the surface.

## Working rules

- Extend existing functions before adding new ones; justify each new one.
- Every contract change: models, regenerate the reference (`scripts/build_yaml_reference.py`),
  the concept-budget test, an ADR.
- Every documented fact has one home (`CONTRIBUTING.md`). Link, do not repeat.
- Tests are offline by default; server tests carry `@pytest.mark.integration`.
- Do not edit `vocabulary.yml` while onboarding; that is the `vocab-review` skill's job.
- Branches, issues, PRs and commits follow `CONTRIBUTING.md` ("Issues, pull requests,
  branches and commits") and the templates in `.github/`. Labels, assignee and reviewers
  are set by a person, not by you.

## Where things are

| | |
|---|---|
| `docs/` | the mkdocs site (diataxis: Guides / Understand / Reference); `docs/adr/` unpublished |
| `docs/reference/dataset-yaml.md` | **generated**; edit `contract.py` |
| `examples/notebook.py` | marimo tour of the read path |
| `scripts/` | maintainer tools (see `CONTRIBUTING.md`) |
| `config.yml`, `config.upload.yml` | server configs: pointer-serving, upload-hosting |
